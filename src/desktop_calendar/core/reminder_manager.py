# coding: utf-8
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QObject, QTimer, QDate, QTime

from desktop_calendar.config.manager import ConfigManager, get_logger, to_bool
from desktop_calendar.core.memorial import get_next_memorial_date
from desktop_calendar.contracts.event_bus import event_bus
from desktop_calendar.contracts.events import EventType
from desktop_calendar.config.i18n import tr

logger = get_logger()


@dataclass(frozen=True)
class _RemindCfg:
    """提醒相关配置的快照。"""
    enable: bool
    start_hour: int
    end_hour: int
    sound_enable: bool


class ReminderManager(QObject):
    """提醒管理器：统一处理纪念日判定与调度。"""

    # QTimer 32 位 int 溢出保护：最大约 24.8 天，超过则按 24 天分段调度
    MAX_DELAY_MS = 24 * 24 * 60 * 60 * 1000

    # 每个纪念日最多尝试的候选周期数。用于 get_next_memorial_date 返回的
    # 候选日期在当前时刻已过（如今天命中但 remind_start_hour 已过）时，
    # 推进 search_base 到下一周期重新取候选。
    #
    # 与 memorial._LUNAR_*_LOOKAHEAD 语义正交：那两个常量是"单次搜索的
    # 深度边界"（农历 13 个月 / 5 年），本常量是"候选已过后的推进次数"，
    # 不能扩展单次搜索的窗口深度。
    MAX_RETRY_PER_MEMORIAL = 4

    def __init__(self, parent_widget, config: ConfigManager, sound_manager=None):
        super().__init__(parent_widget)
        self.parent = parent_widget
        self.config = config
        self.sound_mgr = sound_manager
        self._remind_timer = QTimer(self)
        self._remind_timer.setSingleShot(True)
        self._remind_timer.timeout.connect(self._on_trigger)
        self._is_scheduling = False  # 防重入（仅保护非 force 路径）
        self._pending_remind_date = ""
        self._next_ts_cache: Dict[Tuple, Optional[int]] = {}
        self._cache_day: Optional[str] = None
        self._cache_remind_h: Optional[int] = None

    # ------------------------------------------------------------------ #
    # 配置读取
    # ------------------------------------------------------------------ #
    @staticmethod
    def _get_int_cfg(cfg, *keys, default: int,
                     lo: Optional[int] = None, hi: Optional[int] = None):
        """
        读取 int 配置，兼容浮点/字符串。lo / hi 越界时夹取到边界（而非
        回退 default），保留用户"深夜/凌晨"等意图，与 normalize_memorial
        的夹取风格一致。
        """
        val = cfg.get_nested(*keys, default=default)
        # bool 是 int 子类，必须优先拦截，否则 True→1 / False→0
        if isinstance(val, bool):
            return default
        try:
            v = int(val)
        except (TypeError, ValueError):
            return default
        if lo is not None and v < lo:
            return lo
        if hi is not None and v > hi:
            return hi
        return v

    @staticmethod
    def _get_bool_cfg(cfg, *keys, default: bool):
        """
        安全读取布尔配置。JSON 手改成 1.0 / 0.0 时不应静默回退 default
        （会导致关不掉的提醒）。
        """
        return to_bool(cfg.get_nested(*keys, default=default), default=default)

    def _read_remind_cfg(self) -> _RemindCfg:
        """一次性读取全部提醒相关配置，避免各处重复 get_nested。"""
        bool_cfg = self._get_bool_cfg
        int_cfg = self._get_int_cfg
        return _RemindCfg(
            enable=bool_cfg(
                self.config, "memorial_cfg", "enable_remind", default=True),
            start_hour=int_cfg(
                self.config, "memorial_cfg", "remind_start_hour",
                default=8, lo=0, hi=23),
            end_hour=int_cfg(
                self.config, "memorial_cfg", "remind_end_hour",
                default=22, lo=0, hi=24),
            sound_enable=bool_cfg(
                self.config, "memorial_cfg", "sound_enable", default=True),
        )

    # ------------------------------------------------------------------ #
    # 调度入口
    # ------------------------------------------------------------------ #
    def reschedule(self, force: bool = False, check_today: bool = False,
                   normalized=None):
        if not force:
            if self._is_scheduling:
                logger.debug("提醒调度进行中，忽略重复请求")
                return
            self._is_scheduling = True
        else:
            # 强制重算：数据可能已变，清缓存避免 id 复用导致的误命中
            self._next_ts_cache.clear()

        try:
            cfg = self._read_remind_cfg()
            if not cfg.enable:
                self._remind_timer.stop()
                logger.debug("[提醒调试] 提醒总开关关闭，定时器停止")
                return

            if check_today:
                QTimer.singleShot(0, self.check_memorial)

            next_ts = self._calc_next_timestamp(
                normalized, remind_h=cfg.start_hour)
            if next_ts is None:
                self._remind_timer.stop()
                logger.debug("[提醒调试] 无未来提醒事件，定时器已停止")
                return

            self._schedule_timer(next_ts)

        except Exception:
            logger.exception("[提醒调试] reschedule调度失败")
            self._remind_timer.start(60_000)
        finally:
            if not force:
                self._is_scheduling = False

    def _schedule_timer(self, next_ts: int) -> None:
        """按目标时间戳设置单次定时器，超长间隔分段调度。"""
        now_ms = int(datetime.now().timestamp() * 1000)
        delta_ms = max(0, next_ts - now_ms)

        if delta_ms > self.MAX_DELAY_MS:
            # 分段调度：分段触发只重算时间，不做当日提醒
            self._remind_timer.start(self.MAX_DELAY_MS)
            logger.debug("[提醒调试] 下次提醒间隔超过24天，采用分段调度")
            return

        self._remind_timer.start(delta_ms)
        next_time = datetime.fromtimestamp(
            next_ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(
            "[提醒调试] 下一次提醒已调度：%s，延迟 %.0f 秒",
            next_time, delta_ms / 1000)

    # ------------------------------------------------------------------ #
    # 下一个提醒时间戳
    # ------------------------------------------------------------------ #
    def _calc_next_timestamp(self, normalized=None,
                             remind_h: Optional[int] = None) -> Optional[int]:
        """
        计算所有纪念日最近的未来提醒时间戳(ms)，没有返回 None。

        :param normalized: 预归一化列表；None 时自行读取。
        :param remind_h: 提醒小时；None 时自行读配置。
        """
        if remind_h is None:
            remind_h = self._get_int_cfg(
                self.config, "memorial_cfg", "remind_start_hour",
                default=8, lo=0, hi=23)

        now_dt = datetime.now()
        today_q = QDate(now_dt.year, now_dt.month, now_dt.day)
        self._reset_cache_if_scope_changed(today_q, remind_h)

        if normalized is None:
            normalized = self._enabled_memorials()

        candidates = []
        for mem in normalized:
            ts = self._next_ts_for_memorial(mem, today_q, now_dt, remind_h)
            if ts is not None:
                candidates.append(ts)
        return min(candidates) if candidates else None

    def _reset_cache_if_scope_changed(self, today_q: QDate,
                                      remind_h: int) -> None:
        """跨天或提醒小时变更时清空缓存。"""
        today_str = today_q.toString("yyyy-MM-dd")
        if self._cache_day != today_str or self._cache_remind_h != remind_h:
            self._next_ts_cache.clear()
            self._cache_day = today_str
            self._cache_remind_h = remind_h

    @staticmethod
    def _memorial_cache_key(mem: dict, remind_h: int) -> tuple:
        """构造纪念日缓存键。

        使用 mem 中所有可哈希标量字段 + remind_h，避免漏掉新增的周期字段
        （如 year / 农历相关）导致同一天内编辑纪念日命中旧缓存。name 不
        参与日期计算，不纳入键（改名不应使缓存失效）。不可哈希字段被忽略
        ——若未来引入影响日期计算的复合字段，需在此显式纳入。
        """
        parts = []
        for k, v in mem.items():
            if k == "name":
                continue
            try:
                hash(v)
            except TypeError:
                continue
            parts.append((k, v))
        parts.append(("__remind_h__", remind_h))
        return tuple(sorted(parts))

    def _next_ts_for_memorial(self, mem: dict, today_q: QDate,
                              now_dt: datetime,
                              remind_h: int) -> Optional[int]:
        """计算单个纪念日的最近未来提醒时间戳；无候选返回 None。"""
        ck = self._memorial_cache_key(mem, remind_h)
        if ck in self._next_ts_cache:
            return self._next_ts_cache[ck]

        advance_days = mem.get("advance_days", 0)
        ts = None
        search_base = today_q

        for _ in range(self.MAX_RETRY_PER_MEMORIAL):
            target_date = get_next_memorial_date(
                mem, search_base, include_base=True, normalized=True)
            if target_date is None:
                logger.debug(
                    "[提醒调试] %s：从 %s 起无可计算的候选日期，跳过",
                    mem.get("name", "未命名"),
                    search_base.toString("yyyy-MM-dd"))
                break

            target = QDate(target_date.year, target_date.month,
                           target_date.day)
            first_alert_day = target.addDays(-advance_days)
            if first_alert_day < today_q:
                first_alert_day = today_q

            ts = self._first_future_remind_ts(
                first_alert_day, target, remind_h, now_dt)
            if ts is not None:
                logger.trace(
                    "[提醒调试] %s：目标 %s，提醒时刻 %s",
                    mem.get("name", "未命名"),
                    target.toString("yyyy-MM-dd"),
                    datetime.fromtimestamp(ts / 1000).strftime(
                        "%Y-%m-%d %H:%M"))
                break
            search_base = target.addDays(1)
        else:
            logger.debug(
                "[提醒调试] %s：连续 %d 次候选日期均已过，本次跳过"
                "（advance_days=%s，search_base=%s）",
                mem.get("name", "未命名"),
                self.MAX_RETRY_PER_MEMORIAL,
                advance_days,
                search_base.toString("yyyy-MM-dd"))

        self._next_ts_cache[ck] = ts  # None 也缓存，表示该周期内无候选
        return ts

    @staticmethod
    def _first_future_remind_ts(first_alert_qd: QDate, target_qd: QDate,
                                remind_h: int,
                                now_dt: datetime) -> Optional[int]:
        """
        返回 [first_alert_day, target_day] 区间内第一个未到来的提醒时刻
        （毫秒时间戳）；无候选返回 None。
        """
        now_ms = int(now_dt.timestamp() * 1000)
        today_qd = QDate(now_dt.year, now_dt.month, now_dt.day)
        start = first_alert_qd if first_alert_qd > today_qd else today_qd
        if start == today_qd:
            today_remind = datetime(now_dt.year, now_dt.month, now_dt.day,
                                    remind_h, 0, 0)
            if int(today_remind.timestamp() * 1000) <= now_ms:
                start = start.addDays(1)  # 今天时刻已过 → 明天
        if start > target_qd:
            return None
        dt = datetime(start.year(), start.month(), start.day(), remind_h, 0, 0)
        ts = int(dt.timestamp() * 1000)
        return ts if ts > now_ms else None

    # ------------------------------------------------------------------ #
    # 定时触发
    # ------------------------------------------------------------------ #
    def _on_trigger(self):
        """定时器到期回调。重排由 check_memorial 的 finally 统一负责。"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.debug("[提醒调试] 定时器触发，时间：%s", now_str)
        try:
            self.check_memorial()
        except Exception:
            logger.exception("[提醒调试] check_memorial 异常")

    # ------------------------------------------------------------------ #
    # 当日提醒检查
    # ------------------------------------------------------------------ #
    def check_memorial(self):
        logger.debug("[提醒调试] 开始执行当日纪念日检查")
        all_mem = None
        try:
            cfg = self._read_remind_cfg()
            if not cfg.enable:
                logger.debug("[提醒调试] 提醒总开关关闭，跳过检查")
                return

            today = QDate.currentDate()
            today_str = today.toString("yyyy-MM-dd")
            last = self.config.get_nested(
                "memorial_cfg", "last_remind_date", default="")
            if last == today_str:
                logger.debug("[提醒调试] 今日已提醒过，跳过")
                return

            now_hour = QTime.currentTime().hour()
            if not (cfg.start_hour <= now_hour < cfg.end_hour):
                logger.debug(
                    "[提醒调试] 当前 %d 点不在 %d~%d 提醒窗口内，跳过",
                    now_hour, cfg.start_hour, cfg.end_hour)
                return

            all_mem = self._enabled_memorials()
            hit_list = self._collect_hits(all_mem, today)
            logger.debug(
                "[提醒调试] 检查完成：共 %d 条纪念日，命中 %d 条",
                len(all_mem), len(hit_list))

            if not hit_list:
                logger.debug("[提醒调试] 无命中提醒")
                return

            # 已有待确认的提醒：不重复弹、不重复播声音。
            if self._pending_remind_date:
                logger.debug(
                    "[提醒调试] 已有待确认提醒 %s，跳过本次触发",
                    self._pending_remind_date)
                return

            self._emit_reminder(hit_list, today_str, cfg.sound_enable)
        finally:
            try:
                # 复用本次已算好的列表，省一次全表 normalize
                self.reschedule(check_today=False, normalized=all_mem)
            except Exception:
                logger.exception("[提醒调试] check_memorial 后重排失败")

    @staticmethod
    def _collect_hits(all_mem: list, today: QDate) -> list:
        """扫描纪念日列表，返回命中文本列表。"""
        hit_list = []
        for idx, mem in enumerate(all_mem):
            target_date = get_next_memorial_date(
                mem, today, include_base=True, normalized=True)
            if target_date is None:
                logger.debug(
                    "[提醒调试] %s：无法计算目标日期，跳过",
                    mem.get("name", "未命名"))
                continue

            target = QDate(target_date.year, target_date.month,
                           target_date.day)
            diff = today.daysTo(target)
            advance_days = mem.get("advance_days", 0)

            logger.trace(
                "[提醒调试] [%d] %s：目标 %s，距今日 %d 天，提前 %d 天",
                idx + 1, mem.get("name", "未命名"),
                target.toString("yyyy-MM-dd"), diff, advance_days)

            if 0 <= diff <= advance_days:
                hit_text = ReminderManager._format_hit_text(mem, diff)
                hit_list.append(hit_text)
                logger.debug("[提醒调试]  ✅ 命中提醒：%s", hit_text)
        return hit_list

    @staticmethod
    def _format_hit_text(mem: dict, diff: int) -> str:
        name = mem.get("name") or tr("memorial.default_name")
        if diff == 0:
            return name
        if diff == 1:
            return tr("memorial.remind.hit_fmt_one").format(name=name)
        return tr("memorial.remind.hit_fmt").format(name=name, days=diff)

    def _emit_reminder(self, hit_list: list, today_str: str,
                       sound_enable: bool) -> None:
        """置 pending 并异步发布提醒事件。"""
        # 先置 pending 再异步 publish：
        #  - 置 pending 挡住 publish 排队期间的再次进入；
        #  - QTimer.singleShot 让 check_memorial 快速返回，
        #    不在 exec 的嵌套事件循环里卡住 reschedule。
        self._pending_remind_date = today_str

        if sound_enable and self.sound_mgr:
            self.sound_mgr.play("assets/alert.wav")

        logger.debug(
            "[提醒调试] 发布 MEMORIAL_REMIND_TRIGGERED，命中 %d 条",
            len(hit_list))
        QTimer.singleShot(0, lambda: event_bus.publish(
            EventType.MEMORIAL_REMIND_TRIGGERED,
            hit_list=list(hit_list),
            today_str=today_str,
        ))

    # ------------------------------------------------------------------ #
    # 确认 / 放弃（共用收尾）
    # ------------------------------------------------------------------ #
    def _persist_last_remind_date(self, today_str: str) -> float:
        """写入 last_remind_date 并落盘，返回落盘耗时（ms）。"""
        self.config.set_nested(
            "memorial_cfg", "last_remind_date", today_str, save=False)
        t0 = time.monotonic()
        self.config.flush()
        return (time.monotonic() - t0) * 1000

    def _finish_reminder(self, today_str: str, *, is_abandon: bool,
                         reason: str = "") -> None:
        """确认/放弃的共用收尾：校验 pending → 落盘 → 清 pending。

        与原版行为一致性：
          - pending 不一致时直接忽略，不动状态；
          - 落盘失败时也会清 pending（acknowledge 原版在 try 之前清，
            abandon 原版在 finally 清，统一到 finally 后语义一致）；
          - 落盘耗时 > 50ms 时无论确认/放弃都 warning。

        :param is_abandon: True 表示异常放弃（日志 warning），
            False 表示用户确认（日志 debug）。
        """
        log = logger.warning if is_abandon else logger.debug
        if not today_str or today_str != self._pending_remind_date:
            log("[提醒调试] %s 忽略：today=%r pending=%r reason=%s",
                "abandon" if is_abandon else "acknowledge",
                today_str, self._pending_remind_date, reason or "-")
            return
        try:
            ms = self._persist_last_remind_date(today_str)
            if ms > 50:
                logger.warning(
                    "[提醒调试] last_remind_date 落盘耗时 %.1fms", ms)
            if is_abandon:
                logger.warning(
                    "[提醒调试] 放弃当天提醒 %s（原因：%s），"
                    "已写入 last_remind_date 避免永久挂起",
                    today_str, reason or "unknown")
            else:
                logger.debug(
                    "[提醒调试] 用户已确认，标记 %s 为已提醒（落盘 %.1fms）",
                    today_str, ms)
        except Exception:
            logger.exception("[提醒调试] 写入 last_remind_date 失败")
        finally:
            # 无论落盘成败都清 pending：落盘失败时下次 check_memorial
            # 会重新命中并重试弹窗（last_remind_date 未写，属"未确认"，
            # 重试是合理的；但不会永久挂起）。
            self._pending_remind_date = ""

    def acknowledge_reminder(self, today_str: str) -> None:
        """
        由 presentation 在提醒弹窗关闭后调用，落盘 last_remind_date。

        :param today_str: 事件 payload 里的 today_str；与 pending 不一致
            时直接忽略（防止过期确认覆盖新状态）。
        """
        self._finish_reminder(today_str, is_abandon=False)

    def abandon_reminder(self, today_str: str, reason: str = "") -> None:
        """
        异常路径：释放 pending 并写入 last_remind_date，放弃当天提醒。

        与 acknowledge_reminder 的区别：
        - 语义：异常放弃 vs 用户确认；
        - 日志级别：warning vs debug。

        落盘行为一致——都写 last_remind_date，避免"异常→pending 悬挂→
        当天后续 check_memorial 全被 guard 拦掉"的永久挂起。牺牲当天
        提醒是刻意的止损：异常若为永久性（如 theme 损坏），重试会形成
        "每次 timer 到期弹一次异常"的循环。
        """
        self._finish_reminder(today_str, is_abandon=True, reason=reason)

    # ------------------------------------------------------------------ #
    # 数据获取
    # ------------------------------------------------------------------ #
    def _enabled_memorials(self) -> list:
        """取出启用状态的纪念日列表。

        写入侧（ConfigManager）已保证每条都是 normalize 过的 dict；
        这里只做防御性检查（非 dict / 缺关键字段跳过），不再 normalize。
        advance_days 再做一次 max(0, int) 夹取，防止绕过 ConfigManager
        直接改 _cfg 的意外路径。

        注意：这里对每条 dict 做浅拷贝，避免原地修改污染 ConfigManager
        内部对象（若 config.get 返回的是内部引用）。
        """
        raw_list = self.config.get("memorial_days", [])
        result = []
        for mem in raw_list:
            if not isinstance(mem, dict):
                continue
            if not to_bool(mem.get("enabled"), default=True):
                continue
            if not all(k in mem for k in ("repeat_type", "type", "day", "month")):
                continue
            mem = dict(mem)
            try:
                mem["advance_days"] = max(0, int(mem.get("advance_days", 0)))
            except (TypeError, ValueError):
                mem["advance_days"] = 0
            result.append(mem)
        return result