# coding: utf-8
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QObject, QTimer, QDate, QTime

from desktop_calendar.config.manager import ConfigManager, get_logger, to_bool
from desktop_calendar.core.memorial import (
    get_next_memorial_date, normalize_memorial,
)
from desktop_calendar.contracts.event_bus import event_bus
from desktop_calendar.contracts.events import EventType
from desktop_calendar.config.i18n import tr

logger = get_logger()


@dataclass(frozen=True)
class _RemindCfg:
    enable: bool
    start_hour: int
    end_hour: int
    sound_enable: bool


_REQUIRED_MEMORIAL_FIELDS = ("repeat_type", "type")


class ReminderManager(QObject):
    """提醒管理器：纪念日判定与调度。

    提醒去重采用"命中集合签名"而非"今天是否提醒过"布尔：
    后者在用户当天新增纪念日时会把新命中项一起吞掉（旧行为）。
    签名 = sha256(排序后的命中文本) 的前 16 位，与日期拼接后存
    入 ``memorial_cfg.last_remind_sig``。命中集合变化（新增/删除/
    改名）导致签名变化，从而允许当天再次弹窗。
    """

    MAX_DELAY_MS = 24 * 60 * 60 * 1000
    MAX_RETRY_PER_MEMORIAL = 4

    def __init__(self, parent_widget, config: ConfigManager, sound_manager=None):
        super().__init__(parent_widget)
        self.parent = parent_widget
        self.config = config
        self.sound_mgr = sound_manager
        self._remind_timer = QTimer(self)
        self._remind_timer.setSingleShot(True)
        self._remind_timer.timeout.connect(self._on_trigger)
        self._is_scheduling = False
        self._pending_remind_date = ""
        self._pending_sig = ""          # 当前 pending 提醒对应的签名
        self._next_ts_cache: Dict[Tuple, Optional[int]] = {}
        self._cache_day: Optional[str] = None
        self._cache_remind_h: Optional[int] = None

    # ---------- 配置读取 ----------
    @staticmethod
    def _get_int_cfg(cfg, *keys, default: int,
                     lo: Optional[int] = None, hi: Optional[int] = None):
        val = cfg.get_nested(*keys, default=default)
        if isinstance(val, bool):  # bool 是 int 子类，须先拦截
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
        return to_bool(cfg.get_nested(*keys, default=default), default=default)

    def _read_remind_cfg(self) -> _RemindCfg:
        start = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_start_hour",
            default=8, lo=0, hi=23)
        end = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_end_hour",
            default=22, lo=0, hi=24)
        # start >= end 兜底：normalize_config 已在落盘时修正，但运行期
        # config.set_nested / update_nested 可写入未归一化值，而
        # check_memorial 的 `start <= h < end` 在 start >= end 时恒为
        # False，会导致永久静默不提醒。此处与 normalize_config 保持
        # 一致的"回退默认 8~22"策略，不自动交换（理由见 normalize_config）。
        if start >= end:
            logger.warning(
                "remind 时段非法 start=%s >= end=%s，回退默认 8~22",
                start, end)
            start, end = 8, 22
        return _RemindCfg(
            enable=self._get_bool_cfg(
                self.config, "memorial_cfg", "enable_remind", default=True),
            start_hour=start,
            end_hour=end,
            sound_enable=self._get_bool_cfg(
                self.config, "memorial_cfg", "sound_enable", default=True),
        )

    # ---------- 调度入口 ----------
    def reschedule(self, force: bool = False, check_today: bool = False,
                   normalized=None):
        if not force:
            if self._is_scheduling:
                return
            self._is_scheduling = True
        else:
            self._next_ts_cache.clear()
            # 跨天重排时清掉 pending：昨天的 pending 不应阻塞今天的提醒。
            # 今天的 pending 保留，避免同一天内改动纪念日触发重复弹窗。
            today_str = QDate.currentDate().toString("yyyy-MM-dd")
            if (self._pending_remind_date
                    and self._pending_remind_date != today_str):
                self._pending_remind_date = ""
                self._pending_sig = ""
        try:
            cfg = self._read_remind_cfg()
            if not cfg.enable:
                self._remind_timer.stop()
                return

            if check_today:
                QTimer.singleShot(0, self.check_memorial)

            next_ts = self._calc_next_timestamp(normalized, remind_h=cfg.start_hour)
            if next_ts is None:
                self._remind_timer.stop()
                return
            self._schedule_timer(next_ts)
        except Exception:
            logger.exception("[提醒调试] reschedule 调度失败")
            self._remind_timer.start(60_000)
        finally:
            if not force:
                self._is_scheduling = False

    def _schedule_timer(self, next_ts: int) -> None:
        now_ms = int(datetime.now().timestamp() * 1000)
        delta_ms = max(0, next_ts - now_ms)
        if delta_ms > self.MAX_DELAY_MS:
            self._remind_timer.start(self.MAX_DELAY_MS)
            return
        self._remind_timer.start(delta_ms)
        next_time = datetime.fromtimestamp(next_ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
        logger.debug("[提醒调试] 下一次提醒已调度：%s，延迟 %.0f 秒",
                     next_time, delta_ms / 1000)

    # ---------- 下一个时间戳 ----------
    def _calc_next_timestamp(self, normalized=None,
                             remind_h: Optional[int] = None) -> Optional[int]:
        if remind_h is None:
            remind_h = self._read_remind_cfg().start_hour

        now_dt = datetime.now()
        today_q = QDate(now_dt.year, now_dt.month, now_dt.day)
        self._reset_cache_if_scope_changed(today_q, remind_h)

        if normalized is None:
            normalized = self._enabled_memorials()

        candidates = [ts for mem in normalized
                      if (ts := self._next_ts_for_memorial(
                          mem, today_q, now_dt, remind_h)) is not None]
        return min(candidates) if candidates else None

    def _reset_cache_if_scope_changed(self, today_q: QDate, remind_h: int) -> None:
        today_str = today_q.toString("yyyy-MM-dd")
        if self._cache_day != today_str or self._cache_remind_h != remind_h:
            self._next_ts_cache.clear()
            self._cache_day = today_str
            self._cache_remind_h = remind_h

    @staticmethod
    def _memorial_cache_key(mem: dict, remind_h: int) -> tuple:
        """缓存键：所有可哈希标量字段 + remind_h。name 不影响日期，排除。"""
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
                              now_dt: datetime, remind_h: int) -> Optional[int]:
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
                break

            target = QDate(target_date.year, target_date.month, target_date.day)
            first_alert_day = target.addDays(-advance_days)
            if first_alert_day < today_q:
                first_alert_day = today_q

            ts = self._first_future_remind_ts(
                first_alert_day, target, remind_h, now_dt)
            if ts is not None:
                break
            search_base = target.addDays(1)
        else:
            logger.debug("[提醒调试] %s：连续 %d 次候选均过，跳过",
                         mem.get("name", "未命名"), self.MAX_RETRY_PER_MEMORIAL)

        self._next_ts_cache[ck] = ts
        return ts

    @staticmethod
    def _first_future_remind_ts(first_alert_qd: QDate, target_qd: QDate,
                                remind_h: int, now_dt: datetime) -> Optional[int]:
        now_ms = int(now_dt.timestamp() * 1000)
        today_qd = QDate(now_dt.year, now_dt.month, now_dt.day)
        start = first_alert_qd if first_alert_qd > today_qd else today_qd
        if start == today_qd:
            today_remind = datetime(now_dt.year, now_dt.month, now_dt.day,
                                    remind_h, 0, 0)
            if int(today_remind.timestamp() * 1000) <= now_ms:
                start = start.addDays(1)
        if start > target_qd:
            return None
        dt = datetime(start.year(), start.month(), start.day(), remind_h, 0, 0)
        ts = int(dt.timestamp() * 1000)
        return ts if ts > now_ms else None

    # ---------- 定时触发 ----------
    def _on_trigger(self):
        logger.debug("[提醒调试] 定时器触发，时间：%s",
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            self.check_memorial()
        except Exception:
            logger.exception("[提醒调试] check_memorial 异常")

    # ---------- 命中签名 ----------
    @staticmethod
    def _hits_signature(hit_list: list) -> str:
        """命中列表的稳定签名。

        - 排序后拼接：集合相同则签名相同（顺序无关）。
        - sha256 而非 md5：FIPS 模式下 md5 可能抛 ValueError。
        - 截断 16 位：碰撞概率可忽略（用于本地区分提醒批次，非安全用途）。
        """
        raw = "\x00".join(sorted(hit_list)).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    # ---------- 当日检查 ----------
    def check_memorial(self):
        logger.debug("[提醒调试] 开始执行当日纪念日检查")
        all_mem = None
        try:
            cfg = self._read_remind_cfg()
            if not cfg.enable:
                return

            today = QDate.currentDate()
            today_str = today.toString("yyyy-MM-dd")

            # 旧版本兼容：last_remind_sig 为空说明是升级前写的数据。
            # 此时回退到 last_remind_date 判断"今天是否已提醒"，避免
            # 升级当天老用户被重复弹窗；次日 last_remind_date 变旧，
            # 自然恢复新流程。
            last_sig = self.config.get_nested(
                "memorial_cfg", "last_remind_sig", default="")
            if not last_sig:
                last = self.config.get_nested(
                    "memorial_cfg", "last_remind_date", default="")
                if last == today_str:
                    return

            now_hour = QTime.currentTime().hour()
            if not (cfg.start_hour <= now_hour < cfg.end_hour):
                return

            all_mem = self._enabled_memorials()
            hit_list = self._collect_hits(all_mem, today)
            if not hit_list:
                return

            sig = self._hits_signature(hit_list)
            if last_sig == f"{today_str}:{sig}":
                # 今天已针对同一命中集合提醒过（用户 ack / abandon，
                # 或新增内容不改变命中集合）。不重复弹。
                return
            if self._pending_remind_date:
                # 已有 pending（弹窗排队中 / 用户未处理），不叠加。
                return
            self._emit_reminder(hit_list, today_str, cfg.sound_enable, sig)
        finally:
            try:
                self.reschedule(check_today=False, normalized=all_mem)
            except Exception:
                logger.exception("[提醒调试] check_memorial 后重排失败")

    @staticmethod
    def _collect_hits(all_mem: list, today: QDate) -> list:
        hit_list = []
        for mem in all_mem:
            target_date = get_next_memorial_date(
                mem, today, include_base=True, normalized=True)
            if target_date is None:
                continue
            target = QDate(target_date.year, target_date.month, target_date.day)
            diff = today.daysTo(target)
            # advance_days 已在 _enabled_memorials 中归一化为非负 int，
            # 这里直接比较安全。
            if 0 <= diff <= mem.get("advance_days", 0):
                hit_list.append(ReminderManager._format_hit_text(mem, diff))
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
                       sound_enable: bool, sig: str) -> None:
        # 先置 pending 再异步 publish：挡住排队期间再次进入。
        self._pending_remind_date = today_str
        self._pending_sig = sig
        if sound_enable and self.sound_mgr:
            self.sound_mgr.play("assets/alert.wav")
        QTimer.singleShot(0, lambda: event_bus.publish(
            EventType.MEMORIAL_REMIND_TRIGGERED,
            hit_list=list(hit_list), today_str=today_str))

    # ---------- 确认 / 放弃 ----------
    def _persist_last_remind(self, today_str: str, sig: str) -> float:
        """同时写 last_remind_date（诊断用）与 last_remind_sig（去重用）。"""
        self.config.set_nested(
            "memorial_cfg", "last_remind_date", today_str, save=False)
        if sig:
            self.config.set_nested(
                "memorial_cfg", "last_remind_sig",
                f"{today_str}:{sig}", save=False)
        t0 = time.monotonic()
        self.config.flush()
        return (time.monotonic() - t0) * 1000

    def _finish_reminder(self, today_str: str, *, is_abandon: bool,
                         reason: str = "") -> None:
        log = logger.warning if is_abandon else logger.debug
        if not today_str or today_str != self._pending_remind_date:
            log("[提醒调试] %s 忽略：today=%r pending=%r reason=%s",
                "abandon" if is_abandon else "acknowledge",
                today_str, self._pending_remind_date, reason or "-")
            return
        sig = self._pending_sig
        try:
            ms = self._persist_last_remind(today_str, sig)
            if ms > 50:
                logger.warning("[提醒调试] last_remind 落盘耗时 %.1fms", ms)
            if is_abandon:
                logger.warning("[提醒调试] 放弃当天提醒 %s（原因：%s）",
                               today_str, reason or "unknown")
            else:
                logger.debug("[提醒调试] 用户已确认 %s（落盘 %.1fms）",
                             today_str, ms)
        except Exception:
            logger.exception("[提醒调试] 写入 last_remind 失败")
        finally:
            # 落盘失败也清 pending：内存已更新，同进程内不会重复弹窗；
            # 若 flush 失败，重启后会因磁盘无 last_remind_sig 而重新提醒。
            self._pending_remind_date = ""
            self._pending_sig = ""

    def acknowledge_reminder(self, today_str: str) -> None:
        self._finish_reminder(today_str, is_abandon=False)

    def abandon_reminder(self, today_str: str, reason: str = "") -> None:
        self._finish_reminder(today_str, is_abandon=True, reason=reason)

    # ---------- 数据获取 ----------
    def _enabled_memorials(self) -> list:
        raw_list = self.config.get("memorial_days", [])
        result = []
        for mem in raw_list:
            if not isinstance(mem, dict):
                continue
            if not to_bool(mem.get("enabled"), default=True):
                continue
            if any(mem.get(k) is None for k in _REQUIRED_MEMORIAL_FIELDS):
                logger.debug(
                    "纪念日 %r 缺 repeat_type / type，已跳过提醒",
                    mem.get("name", "<unnamed>"))
                continue
            try:
                mem = normalize_memorial(mem)
            except Exception:
                logger.warning(
                    "纪念日 %r 归一化失败，已跳过提醒",
                    mem.get("name", "<unnamed>"), exc_info=True)
                continue
            result.append(mem)
        return result

    def shutdown(self) -> None:
        """退出时停止调度并丢弃 pending。

        不调用 _persist_last_remind：退出时 pending 通常意味着用户
        还没对提醒弹窗做出选择，写 last_remind_sig 会让下次启动不再
        提醒，违背"未确认 = 下次继续提醒"的语义。只清内存。
        """
        self._remind_timer.stop()
        self._pending_remind_date = ""
        self._pending_sig = ""