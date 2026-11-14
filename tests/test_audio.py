# coding: utf-8
"""SoundManager：winsound 缺失/存在、自定义 wav 缺失回退。"""
import pytest

from desktop_calendar.infrastructure import audio


class TestNoWinsound:
    def test_noop(self, qapp, monkeypatch):
        monkeypatch.setattr(audio, "HAS_WINSOUND", False)
        mgr = audio.SoundManager(None, lambda p: p)
        mgr.play("assets/alert.wav")  # 不抛


class TestFallbackToSystem:
    def test_missing_custom_uses_system(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr(audio, "HAS_WINSOUND", True)
        played = []

        class _W:
            SND_FILENAME = 1
            SND_ASYNC = 2
            SND_ALIAS = 4

            @staticmethod
            def PlaySound(p, flags):
                played.append((p, flags))

        monkeypatch.setattr(audio, "winsound", _W)
        mgr = audio.SoundManager(None, lambda p: str(tmp_path / p))
        mgr.play("assets/alert.wav")
        # 缺失 → 系统 fallback
        assert any("SystemAsterisk" in str(a[0]) for a in played)
        assert any(a[1] & _W.SND_ALIAS for a in played)


class TestPlaysCustom:
    def test_custom_used(self, qapp, tmp_path, monkeypatch):
        wav = tmp_path / "assets" / "alert.wav"
        wav.parent.mkdir()
        wav.write_bytes(b"RIFF")
        monkeypatch.setattr(audio, "HAS_WINSOUND", True)

        played = []

        class _W:
            SND_FILENAME = 1
            SND_ASYNC = 2
            SND_ALIAS = 4

            @staticmethod
            def PlaySound(p, flags):
                played.append((p, flags))

        monkeypatch.setattr(audio, "winsound", _W)
        mgr = audio.SoundManager(None, lambda p: str(tmp_path / p))
        mgr.play("assets/alert.wav")
        assert len(played) == 1
        path, flags = played[0]
        assert path.endswith("alert.wav")
        assert flags & _W.SND_FILENAME


class TestEmptyWavSkipped:
    def test_empty_wav_uses_system(self, qapp, tmp_path, monkeypatch):
        wav = tmp_path / "assets" / "alert.wav"
        wav.parent.mkdir()
        wav.write_bytes(b"")  # 空文件
        monkeypatch.setattr(audio, "HAS_WINSOUND", True)

        played = []

        class _W:
            SND_FILENAME = 1
            SND_ASYNC = 2
            SND_ALIAS = 4

            @staticmethod
            def PlaySound(p, flags):
                played.append((p, flags))

        monkeypatch.setattr(audio, "winsound", _W)
        mgr = audio.SoundManager(None, lambda p: str(tmp_path / p))
        mgr.play("assets/alert.wav")
        # 空文件 → 不预加载 → 系统 fallback
        assert any("SystemAsterisk" in str(a[0]) for a in played)
