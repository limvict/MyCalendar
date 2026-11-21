from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.infrastructure.network import sidebar_services
from desktop_calendar.infrastructure.network.sidebar_services import (
    SidebarServices,
)
from desktop_calendar.ui.theme.bundle import build_bundle
from desktop_calendar.ui.widgets.sidebar_services_widget import (
    SidebarServicesWidget,
)


def test_saying_parser_reads_uapis_random_response():
    assert sidebar_services._ENDPOINT == ("https://uapis.cn/api/v1/saying/random")
    assert (
        SidebarServices._parse_saying(
            {
                "uuid": "quote-id",
                "content": "今天也要好好生活。",
                "source": "test",
            }
        )
        == "今天也要好好生活。\n— test"
    )


def test_saying_parser_accepts_standard_endpoint_response():
    assert SidebarServices._parse_saying({"text": "愿你心中有光。"}) == "愿你心中有光。"


def test_saying_parser_uses_author_as_attribution():
    assert (
        SidebarServices._parse_saying(
            {
                "content": "愿你心中有光。",
                "author": "佚名",
            }
        )
        == "愿你心中有光。\n— 佚名"
    )


def test_saying_parser_rejects_empty_response():
    try:
        SidebarServices._parse_saying({"content": ""})
    except ValueError as error:
        assert "UAPIS" in str(error)
    else:
        raise AssertionError("Expected an empty saying to be rejected")


def test_sidebar_widget_refreshes_random_saying_and_ignores_stale_response(qapp):
    class FakeSource:
        def __init__(self):
            self.requests = []
            self.stopped = False

        def fetch(self, on_success, on_error):
            self.requests.append((on_success, on_error))

        def shutdown(self):
            self.stopped = True

    source = FakeSource()
    widget = SidebarServicesWidget(source)
    widget.apply_theme(build_bundle("light", dict(DEFAULT_THEME)))
    try:
        widget.refresh()
        widget.refresh()
        assert len(source.requests) == 1
        assert widget._quote_label.text() == "正在加载…"

        widget.refresh(force=True)
        assert len(source.requests) == 2
        source.requests[0][0]("旧的一言")
        assert widget._quote_label.text() == "正在加载…"
        source.requests[1][0]("新的一言\n— 佚名")
        # 正文与出处拆开：出处单独一行，正文不含署名
        assert widget._quote_label.text() == "新的一言"
        assert widget._source_label.text() == "—— 佚名"
        assert not widget._source_label.isHidden()

        assert widget._section_button.isChecked()
        assert not widget._refresh_button.isHidden()
        widget._section_button.click()
        assert widget._body.isHidden()
        # 折叠后整行只剩标题，刷新按钮一起收起
        assert widget._refresh_button.isHidden()

        widget._section_button.click()
        widget.refresh(force=True)
        source.requests[-1][1]("服务暂不可用")
        assert "暂时拿不到今日灵感" in widget._quote_label.text()
        assert "服务暂不可用" in widget._quote_label.text()
        assert "服务暂不可用" in widget._quote_label.toolTip()
        assert widget._source_label.isHidden()
    finally:
        widget.stop()
        assert source.stopped
        widget.deleteLater()
