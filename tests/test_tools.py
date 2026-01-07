
from wyoming_gemini_live.tools import build_tools

def test_build_tools():
    tools = build_tools()
    assert len(tools) == 1
    tool = tools[0]
    
    # Check it has control_home_assistant
    funcs = tool.function_declarations
    assert len(funcs) == 1
    assert funcs[0].name == "control_home_assistant"
    
    # Check parameters
    props = funcs[0].parameters.properties
    assert "domain" in props
    assert "service" in props
    assert "entity_id" in props
