"""Helpers for the Playwright e2e suite, one module per area.

Every public name, and every private one the suite imports, is imported here
from the module that holds it, so ``from .utils import X`` keeps working.
Patch a name in the module whose code looks it up when it runs: for the names
``save_workflow_test_screenshot`` and ``frame_nodes`` call, that is
``utils.screenshots``, wherever the name is defined. A patch here changes only
this copy, not what the helpers call.
"""

# Code-shaping helpers live in workflow_spec (no pytest/playwright imports)
# so the non-browser runners -- this module and tests/stress -- can share
# them. Re-exported here because call sites across the suite import them
# from utils.
from ..workflow_spec import resolve_code_references, seed_node_code  # noqa: F401
from .environment import (  # noqa: F401
    REPO_ROOT,
    state_root,
    env_flag,
    auth_enabled_env,
    allow_guest_login_env,
    skip_project_page_env,
    require_user_auth,
    require_project_page,
    require_no_project_mode,
    debug_log,
)
from .sandbox import (  # noqa: F401
    SANDBOX_CONNECT_TIMEOUT_S,
    SANDBOX_GET_TIMEOUT_S,
    get_shared_data_dir,
    sandbox_auth_header,
    sandbox_base_url,
    load_artifact_as_dict,
    execute_workflow_programmatically,
)
from .vega_svg import (  # noqa: F401
    PLAYWRIGHT_EXPECTED_DIR,
    dot_data_to_vega_values,
    save_expected_svg,
    load_expected_svg,
    compare_svg_structure,
)
from .capture_waits import (  # noqa: F401
    _wait_for_reactflow_ready,
    dismiss_toasts,
    WEBFONT_FAMILY,
    WEBFONT_TIMEOUT_MS,
    _wait_for_webfont,
    NODE_SETTLE_TIMEOUT_MS,
    _wait_for_no_node_running,
)
from .images import _compare_images  # noqa: F401
from .dialogs import accept_confirm_dialog, leave_agent_badge  # noqa: F401
from .screenshots import (  # noqa: F401
    WORKFLOW_SCREENSHOT_EXPECTED_DIR,
    dump_browser_log,
    REMINT_HOW,
    allow_baseline_writes,
    REMINT_MIN_RATIO,
    VOLATILE_TEXT,
    MAX_DIFF_RATIO,
    save_workflow_test_screenshot,
    park_pointer,
    frame_nodes,
)
from .closeups import (  # noqa: F401
    CLOSEUP_PIXEL_THRESHOLD,
    CLOSEUP_MAX_DIFF_RATIO,
    VIEWPORT_SETTLE_WAIT_MS,
    empty_pane_point,
    viewport_will_change,
    watch_viewport_hint,
    viewport_hints,
    canvas_painted_at_shown_zoom,
    save_node_closeup,
)
from .interactions import (  # noqa: F401
    INTERACTION_MIN_CHANGED_PIXELS,
    INTERACTION_VIEWPORT,
    INTERACTION_RESTORED_RATIO,
    drawing_selector,
    keep_drawing,
    drawing_kept,
    mark_point,
    brush_area,
    at_fraction,
    assert_in_view,
    AUTK_PLOT_HIGHLIGHT,
    bar_boxes,
    watch_brush,
    brush_log,
    watch_bar_fills,
    bar_fill_log,
    brush_mismatches,
    _LIT_MARKS_JS,
    lit_marks,
    capture_node,
    changed_pixels,
    wait_for_node_capture,
    wait_for_node_still,
    save_interaction_frame,
)
from .servers import (  # noqa: F401
    is_port_in_use,
    wait_for_http_ready,
    wait_for_port,
    e2e_existing_servers,
    base_url,
)
from .auth import (  # noqa: F401
    DEFAULT_TEST_PASSWORD,
    signup_e2e_user,
    wait_for_projects_page,
    project_card,
    open_new_workflow,
    signup_and_enter_new_workflow,
    require_owner_view,
)
from .db_stubs import (  # noqa: F401
    SESSION_COOKIE_NAME,
    HTTP_TIMEOUT_S,
    _post_json,
    api_json,
    install_session_cookie,
    stub_db_user,
    stub_db_login,
    stub_login_and_enter_workflow,
)
from .palettes import (  # noqa: F401
    open_tools_palette,
    click_package_summary_action,
    close_tools_palette,
)
from .upload import upload_workflow  # noqa: F401
from .canvas_authoring import (  # noqa: F401
    CANVAS_DROP_TARGET,
    _DRAG_TO_CANVAS_JS,
    edge_client_point,
    canvas_nodes,
    canvas_node_type,
    node_locator,
    enable_save_output,
    save_dataflow,
    save_dataflow_and_settle_header,
    frame_node,
    drag_to_canvas,
    set_node_code,
    read_node_code,
    connect_nodes,
    EXPORT_DOWNLOAD_TIMEOUT_MS,
    node_execution_timeout_ms,
    read_node_error_text,
    read_node_output_text,
    activate_header_icon,
    play_node,
    wait_for_node_settled,
    wait_for_node_done,
    run_node_and_wait,
    set_canvas_zoom,
)
from .run_all import (  # noqa: F401
    RUN_ALL_BUTTON_NAME,
    RUN_ALL_BUTTON_SELECTOR,
    run_all_button,
    watch_run_all,
    wait_for_run_all_to_end,
    run_all_and_wait,
    wait_for_run_guard_released,
    backend_url_of,
    hold_server_runs,
    held_server_nodes,
    hold_node_execution,
    wait_for_held_node_execution,
    held_node_executions,
    release_node_execution,
    SandboxRuns,
)
from .node_drawings import (  # noqa: F401
    VEGA_CANVAS_PROBE_JS,
    assert_vega_canvas_rendered,
    _AUTK_MAP_PIXELS_JS,
    assert_autark_map_drawn,
    assert_autark_drawing_fits,
    assert_vega_node_empty_state,
)
from .page import FrontendPage  # noqa: F401
from .scripted_llm import (  # noqa: F401
    SCRIPTED_MODEL,
    SCRIPTED_LABEL,
    use_scripted_llm,
    script_agent_replies,
    captured_agent_prompts,
    captured_agent_calls,
    captured_agent_offers,
    captured_system_prompt,
    reset_agent_script,
)
