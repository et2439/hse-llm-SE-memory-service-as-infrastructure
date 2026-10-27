"""Recompute the planning budget; never presents estimates as telemetry."""
from __future__ import annotations

import json
from pathlib import Path


def calculate(p: dict) -> dict:
    shares = p["write_share"] + p["read_share"] + p["forget_share"]
    if abs(shares - 1) > 1e-9:
        raise ValueError("Operation shares must sum to one")
    n = p["operations_per_day"] * p["days_per_month"]
    writes, reads, forgets = (n * p[k] for k in ("write_share", "read_share", "forget_share"))
    def llm(i, o):
        return (i * p["llm_input_per_million"] + o * p["llm_output_per_million"]) / 1_000_000
    write = p["write_llm_calls"] * llm(p["write_input_tokens_per_call"], p["write_output_tokens_per_call"])
    forget = llm(p["forget_input_tokens"], p["forget_output_tokens"])
    embeddings = (writes * p["write_embedding_tokens"] + reads * p["query_embedding_tokens"]) * p["embedding_per_million"] / 1_000_000
    memory_api = writes * write + forgets * forget + embeddings
    agent = reads * llm(p["agent_fixed_input_tokens"] + p["agent_memory_tokens"], p["agent_output_tokens"])
    reserve = 1 + p["reserve_share"]
    core = (memory_api + p["memory_infrastructure_per_month"]) * reserve
    return {
        "status": "estimates_not_measurements", "monthly_operations": n,
        "writes": round(writes), "reads": round(reads), "forgets": round(forgets),
        "write_extraction_usd": round(writes * write, 6),
        "forget_resolution_usd": round(forgets * forget, 6),
        "embeddings_usd": round(embeddings, 6),
        "memory_api_usd": round(memory_api, 6),
        "memory_service_with_reserve_usd": round(core, 2),
        "memory_service_usd_per_1000_operations": round(core * 1000 / n, 4),
        "answering_agent_usd_before_reserve": round(agent, 6),
        "baseline_total_with_agent_usd": round((agent + p["baseline_infrastructure_per_month"]) * reserve, 2),
        "memory_total_with_agent_usd": round((agent + memory_api + p["memory_infrastructure_per_month"]) * reserve, 2),
        "memory_service_within_cap": core <= p["memory_service_monthly_cap"],
    }


if __name__ == "__main__":
    params = json.loads(Path(__file__).with_name("budget_inputs.json").read_text())
    report = {"base": calculate(params), "sensitivity": {}}
    for factor in (0.5, 2, 10):
        changed = dict(params, operations_per_day=params["operations_per_day"] * factor)
        report["sensitivity"][f"load_x{factor}"] = calculate(changed)
    print(json.dumps(report, ensure_ascii=False, indent=2))
