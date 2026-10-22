from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict, total=False):
    message: str
    route: Literal["capabilities", "general"]
    tool_result: str
    answer: str
    steps: list[str]


def route(state: State) -> State:
    selected: Literal["capabilities", "general"] = (
        "capabilities" if "capabilit" in state["message"].lower() else "general"
    )
    return {"route": selected, "steps": ["route"]}


def capabilities(state: State) -> State:
    # Static allowlisted tool. Never reads the database, executes SQL or mutates finance records.
    return {
        "tool_result": "Core REST scaffold: accounts and transactions. Advisor: offline workflow.",
        "steps": [*state["steps"], "capabilities"],
    }


def respond(state: State) -> State:
    # Replace through a reviewed provider adapter later. No LLM/network calls in this scaffold.
    return {
        "answer": state.get(
            "tool_result",
            "The LangGraph workflow is running in offline stub mode. "
            "No model or financial tools are connected.",
        ),
        "steps": [*state["steps"], "respond"],
    }


def build_graph() -> Any:
    builder = StateGraph(State)
    builder.add_node("route", route)
    builder.add_node("capabilities", capabilities)
    builder.add_node("respond", respond)
    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route",
        lambda state: state["route"],
        {"capabilities": "capabilities", "general": "respond"},
    )
    builder.add_edge("capabilities", "respond")
    builder.add_edge("respond", END)
    # No shared checkpointer: requests cannot read each other's conversation state.
    return builder.compile()
