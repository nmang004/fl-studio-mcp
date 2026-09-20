"""FL Studio MCP tools."""

from fl_studio_mcp.tools.batch import register_batch_tools
from fl_studio_mcp.tools.channels import register_channel_tools
from fl_studio_mcp.tools.describe import register_describe_tools
from fl_studio_mcp.tools.eq import register_eq_tools
from fl_studio_mcp.tools.indexing import register_index_tools
from fl_studio_mcp.tools.journal import register_journal_tools
from fl_studio_mcp.tools.metering import register_metering_tools
from fl_studio_mcp.tools.mixer import register_mixer_tools
from fl_studio_mcp.tools.patterns import register_pattern_tools
from fl_studio_mcp.tools.piano_roll import register_piano_roll_tools
from fl_studio_mcp.tools.plugins import register_plugin_tools
from fl_studio_mcp.tools.presets import register_preset_tools
from fl_studio_mcp.tools.project import register_browser_tools, register_project_tools
from fl_studio_mcp.tools.review import register_review_tools
from fl_studio_mcp.tools.riffs import register_riff_tools
from fl_studio_mcp.tools.routing import register_routing_tools
from fl_studio_mcp.tools.samples import register_sample_tools
from fl_studio_mcp.tools.score import register_score_tools
from fl_studio_mcp.tools.snapshots import register_snapshot_tools
from fl_studio_mcp.tools.structure import register_structure_tools
from fl_studio_mcp.tools.templates import register_template_tools
from fl_studio_mcp.tools.tempo import register_tempo_tools
from fl_studio_mcp.tools.transport import register_transport_tools

__all__ = [
    "register_transport_tools",
    "register_mixer_tools",
    "register_channel_tools",
    "register_plugin_tools",
    "register_piano_roll_tools",
    "register_batch_tools",
    "register_pattern_tools",
    "register_eq_tools",
    "register_routing_tools",
    "register_project_tools",
    "register_tempo_tools",
    "register_score_tools",
    "register_describe_tools",
    "register_metering_tools",
    "register_review_tools",
    "register_journal_tools",
    "register_riff_tools",
    "register_sample_tools",
    "register_snapshot_tools",
    "register_preset_tools",
    "register_browser_tools",
    "register_index_tools",
    "register_structure_tools",
    "register_template_tools",
]
