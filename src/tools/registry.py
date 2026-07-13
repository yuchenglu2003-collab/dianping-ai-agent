from __future__ import annotations

from src.tools.base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"未注册工具: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> dict[str, BaseTool]:
        return dict(self._tools)


def build_default_registry() -> ToolRegistry:
    from src.tools.business.funnel_metrics import FunnelMetricsTool
    from src.tools.business.rfm_segment import RfmSegmentTool
    from src.tools.data.clean_table import CleanTableTool
    from src.tools.data.data_profile import DataProfileTool
    from src.tools.data.setup_check import SetupCheckTool
    from src.tools.ml.rating_predict import RatingPredictTool
    from src.tools.ml.sales_forecast import SalesForecastTool
    from src.tools.nlp.attribution_aspects import AttributionAspectsTool
    from src.tools.nlp.make_wordcloud import MakeWordcloudTool
    from src.tools.nlp.tokenize_jieba import TokenizeJiebaTool
    from src.tools.report.llm_render_report import LLMRenderReportTool
    from src.tools.report.render_report import RenderReportTool
    from src.tools.viz.eda_timeseries import EdaTimeseriesTool
    from src.tools.viz.plot_distributions import PlotDistributionsTool

    registry = ToolRegistry()
    for tool in [
        SetupCheckTool(),
        DataProfileTool(),
        CleanTableTool(),
        PlotDistributionsTool(),
        EdaTimeseriesTool(),
        TokenizeJiebaTool(),
        MakeWordcloudTool(),
        AttributionAspectsTool(),
        RatingPredictTool(),
        FunnelMetricsTool(),
        RfmSegmentTool(),
        SalesForecastTool(),
        LLMRenderReportTool(),
        RenderReportTool(),
    ]:
        registry.register(tool)
    return registry
