# coding: utf-8
"""SettingDialog._import_config 的 merge 语义契约测试。

关注点：导入文件只含部分 memorial_cfg 字段时，应字段级 merge，
而不是整体替换掉用户在对话框里已做但未保存的改动。
"""
import json

from PyQt6.QtWidgets import QFileDialog

from desktop_calendar.ui.dialogs import SettingDialog


def _make_dlg(cfg=None):
    return SettingDialog(
        cfg=cfg or {},
        auto_start_state=False,
        topmost_state=False,
        opacity=0.9,
        memorial_remind=True,
        memorial_sound=True,
    )


def _fake_open(monkeypatch, tmp_path, payload):
    path = tmp_path / "imported.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (str(path), ""),
    )
    return path


def test_import_config_merges_memorial_cfg_fields(qapp, monkeypatch, tmp_path):
    """回归：导入文件 {"memorial_cfg": {"enable_remind": True}} 时，
    用户已改的 sound_enable / remind_start_hour 不应被清掉。

    修复前实现是 `self.cfg[k] = v` 的顶层浅 merge，会把整个
    memorial_cfg 换成导入文件里的单字段 dict。
    """
    dlg = _make_dlg({
        "memorial_cfg": {
            "enable_remind": False,
            "sound_enable": False,
            "remind_start_hour": 9,
        },
    })
    _fake_open(monkeypatch, tmp_path, {
        "memorial_cfg": {"enable_remind": True},
    })

    dlg._import_config()

    mem = dlg.cfg["memorial_cfg"]
    assert mem["enable_remind"] is True     # 导入值生效
    assert mem["sound_enable"] is False     # 用户改动保留
    assert mem["remind_start_hour"] == 9    # 用户改动保留


def test_import_config_keeps_other_top_level_keys(qapp, monkeypatch, tmp_path):
    """顶层键语义仍是"文件里出现才覆盖"：文件不含 language 时，
    对话框里当前的 language 应保留。"""
    dlg = _make_dlg({
        "language": "en_US",
        "topmost": True,
    })
    _fake_open(monkeypatch, tmp_path, {"opacity": 0.7})

    dlg._import_config()

    assert dlg.cfg["opacity"] == 0.7        # 导入值生效
    assert dlg.cfg["language"] == "en_US"   # 未出现在文件里 → 保留
    assert dlg.cfg["topmost"] is True


def test_import_config_overrides_non_dict_memorial_cfg(
        qapp, monkeypatch, tmp_path):
    """当前 cfg 里的 memorial_cfg 不是 dict（脏数据 / 手工改过）时，
    走整体替换分支，不抛异常。"""
    dlg = _make_dlg()
    dlg.cfg["memorial_cfg"] = None

    _fake_open(monkeypatch, tmp_path, {
        "memorial_cfg": {"enable_remind": False},
    })

    dlg._import_config()

    assert dlg.cfg["memorial_cfg"] == {"enable_remind": False}


def test_init_tolerates_none_cfg_fields(qapp):
    dlg = _make_dlg({"memorial_days": None, "memorial_cfg": None})
    assert dlg.cfg["memorial_days"] == []
    assert dlg.cfg["memorial_cfg"] == {}
    assert dlg.get_memorial_list() == [] 
