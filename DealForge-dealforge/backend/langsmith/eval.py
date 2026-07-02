from dotenv import load_dotenv

load_dotenv()

from langsmith.evaluation import evaluate
from langsmith import Client
from core import process_user_input

client = Client()


# =========================
# SHARED EVALUATION RUNNER
# =========================
def run_eval(dataset_name, evaluator):
    return evaluate(
        lambda x: process_user_input(x["input"]),
        data=dataset_name,
        evaluators=[evaluator],
    )


# =========================
# 1. ROUTER EVALUATOR
# =========================
def router_evaluator(run, example):

    output = run.outputs or {}
    expected = example.outputs or {}

    score = 0.0
    feedback = []

    if output.get("tool_used") == expected.get("expected_tool"):
        score += 0.5
    else:
        feedback.append(
            f"Tool mismatch: expected {expected.get('expected_tool')}, got {output.get('tool_used')}"
        )

    if output.get("intent") == expected.get("expected_intent"):
        score += 0.5
    else:
        feedback.append(
            f"Intent mismatch: expected {expected.get('expected_intent')}, got {output.get('intent')}"
        )

    return {
        "key": "router_score",
        "score": score,
        "comment": " | ".join(feedback) if feedback else "perfect",
    }


# =========================
# 2. MEMORY EVALUATOR
# =========================
def memory_evaluator(run, example):

    output = run.outputs or {}
    expected = example.outputs or {}

    score = 0.0
    feedback = []

    # tool correctness
    if output.get("tool_used") == expected.get("expected_tool"):
        score += 0.4
    else:
        feedback.append("Wrong tool")

    # intent correctness
    if output.get("intent") == expected.get("expected_intent"):
        score += 0.3
    else:
        feedback.append("Wrong intent")

    # memory signal (important for DealForge)
    if output.get("memory_used") is True:
        score += 0.3
    else:
        feedback.append("Memory not used")

    return {
        "key": "memory_score",
        "score": score,
        "comment": " | ".join(feedback) if feedback else "perfect",
    }


# =========================
# 3. ANALYTICS EVALUATOR
# =========================
def analytics_evaluator(run, example):

    output = run.outputs or {}
    expected = example.outputs or {}

    score = 0.0
    feedback = []

    if output.get("tool_used") == expected.get("expected_tool"):
        score += 0.5
    else:
        feedback.append("Wrong analytics tool")

    if output.get("intent") == expected.get("expected_intent"):
        score += 0.5
    else:
        feedback.append("Wrong analytics intent")

    return {
        "key": "analytics_score",
        "score": score,
        "comment": " | ".join(feedback) if feedback else "perfect",
    }


# =========================
# 4. RAG EVALUATOR
# =========================
def rag_evaluator(run, example):

    output = run.outputs or {}
    expected = example.outputs or {}

    score = 0.0

    if output.get("tool_used") == expected.get("expected_tool"):
        score += 0.5

    if output.get("intent") == expected.get("expected_intent"):
        score += 0.5

    return {
        "key": "rag_score",
        "score": score,
        "comment": "ok" if score == 1 else "needs improvement",
    }


# =========================
# 5. APPROVAL EVALUATOR
# =========================
def approval_evaluator(run, example):

    output = run.outputs or {}
    expected = example.outputs or {}

    score = 0.0
    feedback = []

    if output.get("tool_used") == expected.get("expected_tool"):
        score += 0.6
    else:
        feedback.append("Wrong approval tool")

    if output.get("intent") == expected.get("expected_intent"):
        score += 0.4
    else:
        feedback.append("Wrong approval intent")

    return {
        "key": "approval_score",
        "score": score,
        "comment": " | ".join(feedback) if feedback else "perfect",
    }


# =========================
# 6. RUN ALL EVALUATIONS
# =========================
if __name__ == "__main__":

    run_eval("dealforge-router", router_evaluator)
    run_eval("dealforge-memory", memory_evaluator)
    run_eval("dealforge-analytics", analytics_evaluator)
    # run_eval("dealforge-rag", rag_evaluator)
    # run_eval("dealforge-approval", approval_evaluator)
