"""OpenAI advisory reviewer for immutable V2 complete-target artifacts."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from typing import Any, Callable
from .openai_reviewer import _require_client, _serialize_contract
from .v2_advisory import V2AdvisoryStatus, V2ReviewerResult

class OpenAIV2Reviewer:
    def __init__(self, *, client=None, model: str | None = None, reasoning_effort: str | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self._client = client
        self._model = (model or os.environ.get("OPENAI_V2_REVIEWER_MODEL") or "gpt-5.6-terra").strip()
        self._effort = (reasoning_effort or os.environ.get("OPENAI_V2_REVIEWER_REASONING_EFFORT") or "low").strip()
        if not self._model or self._effort not in {"low", "medium", "high"}: raise ValueError("invalid V2 reviewer configuration")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
    def review(self, *, portfolio, target, plan, system_safety, manager_risk, research, reviewed_at=None) -> V2ReviewerResult:
        payload = _serialize_contract({"portfolio": portfolio, "target": target, "plan": plan, "system_safety": system_safety, "manager_risk": manager_risk, "research": research})
        schema={"type":"json_schema","name":"v2_reviewer","strict":True,"schema":{"type":"object","additionalProperties":False,"required":["status","findings","rationale"],"properties":{"status":{"type":"string","enum":["RECORDED","ATTENTION"]},"findings":{"type":"array","items":{"type":"string"}},"rationale":{"type":"string"}}}}
        try:
            responses=(self._client.responses if self._client is not None else _require_client().responses)
            response=responses.create(model=self._model,input=[{"role":"system","content":[{"type":"input_text","text":"You are an advisory V2 portfolio reviewer. Never approve, reject, trade, resize, or override System Safety. Return only structured output."}]},{"role":"user","content":[{"type":"input_text","text":json.dumps(payload,sort_keys=True)}]}],text={"format":schema},reasoning={"effort":self._effort},store=False)
        except Exception as error: raise RuntimeError("OpenAIV2Reviewer provider call failed") from error
        if getattr(response,"status",None)!="completed": raise RuntimeError("OpenAIV2Reviewer response was not completed")
        try:
            result = json.loads(response.output_text)
            if not isinstance(result, dict) or set(result) != {"status", "findings", "rationale"}:
                raise ValueError("response must match the V2 reviewer schema")
            if not isinstance(result["findings"], list) or not all(isinstance(item, str) for item in result["findings"]):
                raise ValueError("findings must be an array of strings")
            if not isinstance(result["rationale"], str):
                raise ValueError("rationale must be a string")
            status = V2AdvisoryStatus(result["status"])
            findings = tuple(result["findings"])
            rationale = result["rationale"]
        except Exception as error: raise ValueError("OpenAIV2Reviewer received malformed structured output") from error
        return V2ReviewerResult(portfolio,target,plan,system_safety,manager_risk,research,status,findings,rationale,reviewed_at or self._clock(),"openai-v2-reviewer","v1","openai",self._model)
