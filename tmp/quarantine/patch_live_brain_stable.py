from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing block: {label}")
    return text.replace(old, new, 1)


base = Path("/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-stable-run/python-core")
models = base / "contracts/models.py"
server = base / "api/server.py"
brain = base / "pipeline/steps/live_brain_service.py"
finalizer = base / "pipeline/steps/live_finalizer.py"


text = models.read_text()
text = replace_once(
    text,
    """class BrainSnapshot(BaseModel):
    \"\"\"Immutable snapshot consumed by the live brain.\"\"\"
    session_id: str = \"\"
    utterance_id: str = \"\"
    revision_id: int = 0
    snapshot_text: str = \"\"
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    snapshot_hash: str = \"\"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
""",
    """class BrainSnapshot(BaseModel):
    \"\"\"Immutable snapshot consumed by the live brain.\"\"\"
    session_id: str = \"\"
    utterance_id: str = \"\"
    revision_id: int = 0
    snapshot_text: str = \"\"
    active_question_text: str = \"\"
    active_turns: list[dict[str, Any]] = Field(default_factory=list)
    historical_turns: list[dict[str, Any]] = Field(default_factory=list)
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    primary_question_source: str = \"none\"
    active_ask_key: str = \"\"
    snapshot_hash: str = \"\"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
""",
    "BrainSnapshot",
)
models.write_text(text)


text = server.read_text()
text = replace_once(
    text,
    """def _should_trust_live_brain_draft(plan: Optional[BrainPlan]) -> bool:
    if plan is None:
        return False
    plan_source = str(plan.plan_source or \"\").strip().lower()
    if plan_source not in {\"llm_fast\", \"cached_stable\"}:
        return False
    return bool(str(plan.draft_answer or \"\").strip())
""",
    """def _should_trust_live_brain_draft(plan: Optional[BrainPlan]) -> bool:
    if plan is None:
        return False
    plan_source = str(plan.plan_source or \"\").strip().lower()
    if plan_source != \"llm_fast\":
        return False
    return bool(str(plan.draft_answer or \"\").strip())
""",
    "trust brain draft",
)
text = replace_once(
    text,
    """def _is_cached_stable_brain_plan_compatible(
    stable_plan: Optional[BrainPlan],
    current_plan: Optional[BrainPlan],
    snapshot_text: str,
) -> bool:
    if stable_plan is None or current_plan is None:
        return False
    stable_asks = [
        _normalize_live_question_text(ask).rstrip(\"?.!\").lower()
        for ask in list(stable_plan.ordered_asks or [])
        if _normalize_live_question_text(ask)
    ]
    if not stable_asks:
        return False
    searchable_snapshot = _normalize_live_question_text(snapshot_text).lower()
    searchable_raw = [
        _normalize_live_question_text(ask).lower()
        for ask in list(current_plan.raw_detected_asks or [])
        if _normalize_live_question_text(ask)
    ]
    lead = stable_asks[0]
    if not lead:
        return False
    if lead in searchable_snapshot:
        return True
    return any(lead in ask for ask in searchable_raw)
""",
    """def _is_cached_stable_brain_plan_compatible(
    stable_plan: Optional[BrainPlan],
    current_plan: Optional[BrainPlan],
    snapshot_text: str,
) -> bool:
    if stable_plan is None or current_plan is None:
        return False
    stable_question = _normalize_live_question_text(_build_live_question_from_brain_plan(stable_plan)).lower()
    current_question = _normalize_live_question_text(
        _build_live_question_from_brain_plan(current_plan, snapshot_text)
    ).lower()
    if not stable_question or not current_question:
        return False
    return stable_question == current_question
""",
    "cached stable compatibility",
)
text = replace_once(
    text,
    """    def _live_brain_plan_ready_for_snapshot_v3(
        self,
        *,
        brain_snapshot: BrainSnapshot,
    ) -> bool:
        latest_snapshot = self._latest_brain_snapshot_v3
        latest_plan = self._latest_brain_plan_v3
        if latest_snapshot is None or latest_plan is None:
            return False
        if latest_snapshot.snapshot_hash != brain_snapshot.snapshot_hash:
            return False
        if not list(latest_plan.ordered_asks or []):
            return False
        return self._brain_plan_completeness_rank(latest_plan) >= 3
""",
    """    def _live_brain_plan_ready_for_snapshot_v3(
        self,
        *,
        brain_snapshot: BrainSnapshot,
    ) -> bool:
        latest_snapshot = self._latest_brain_snapshot_v3
        latest_plan = self._latest_brain_plan_v3
        if latest_snapshot is None or latest_plan is None:
            return False
        if latest_snapshot.snapshot_hash != brain_snapshot.snapshot_hash:
            return False
        if str(latest_plan.plan_source or \"\").strip().lower() != \"llm_fast\":
            return False
        if latest_snapshot.active_ask_key and brain_snapshot.active_ask_key:
            if latest_snapshot.active_ask_key != brain_snapshot.active_ask_key:
                return False
        if not list(latest_plan.ordered_asks or []):
            return False
        return self._brain_plan_completeness_rank(latest_plan) >= 3
""",
    "plan ready",
)
text = replace_once(
    text,
    """        if plan_source not in {\"llm_fast\", \"safe_fallback\", \"cached_stable\"}:
            return
""",
    """        if plan_source != \"llm_fast\":
            return
""",
    "warm from plan source gate",
)
text = replace_once(
    text,
    """    def _build_live_brain_snapshot_v3(
        self,
        *,
        limit: int = 5,
        turn_window: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[BrainSnapshot]:
        # The brain should think over the same consolidated conversation history
        # that Capture preserves and Emit will later send downstream.
        if turn_window is None:
            _, turn_window, _ = self._resolve_live_active_context_bundle(limit=limit)
        if not turn_window:
            return None
        snapshot_text = _build_live_brain_snapshot_text(turn_window)
        if not snapshot_text:
            return None
        snapshot_hash = _build_live_brain_snapshot_hash(turn_window)
        return BrainSnapshot(
            session_id=self._session_id,
            utterance_id=f\"{self._session_id}:{self._completed_interviewer_turn_count}\",
            revision_id=max(1, self._latest_interviewer_generation),
            snapshot_text=snapshot_text,
            conversation_history=turn_window,
            snapshot_hash=snapshot_hash,
            timestamp=datetime.utcnow(),
        )
""",
    """    def _build_live_brain_snapshot_v3(
        self,
        *,
        limit: int = 5,
        turn_window: Optional[list[dict[str, Any]]] = None,
        raw_context_bundle: Optional[dict[str, Any]] = None,
    ) -> Optional[BrainSnapshot]:
        # The brain should think over the active interviewer ask plus the exact
        # supporting context split that silence resolution already produced.
        if turn_window is None or raw_context_bundle is None:
            _, resolved_turn_window, resolved_context_bundle = self._resolve_live_active_context_bundle(limit=limit)
            if turn_window is None:
                turn_window = resolved_turn_window
            if raw_context_bundle is None:
                raw_context_bundle = resolved_context_bundle
        if not turn_window:
            return None

        raw_context_bundle = raw_context_bundle or {}
        active_turns = list(raw_context_bundle.get(\"active_turns\") or [])
        historical_turns = list(raw_context_bundle.get(\"historical_turns\") or [])
        active_question_text = _normalize_live_question_text(
            raw_context_bundle.get(\"primary_question\")
            or \"\\n\".join(
                _normalize_live_question_text(turn.get(\"text\") or \"\")
                for turn in active_turns
                if _normalize_live_question_text(turn.get(\"text\") or \"\")
            )
        )
        snapshot_text = active_question_text or _build_live_brain_snapshot_text(turn_window)
        if not snapshot_text:
            return None
        active_ask_state = raw_context_bundle.get(\"active_ask_state\") or {}
        active_ask_key = str(active_ask_state.get(\"ask_key\") or \"\").strip().lower()
        if not active_ask_key:
            active_ask_key = _normalize_live_question_text(active_question_text or snapshot_text).lower()
        snapshot_hash = _build_live_brain_snapshot_hash(turn_window)
        return BrainSnapshot(
            session_id=self._session_id,
            utterance_id=f\"{self._session_id}:{self._completed_interviewer_turn_count}\",
            revision_id=max(1, self._latest_interviewer_generation),
            snapshot_text=snapshot_text,
            active_question_text=active_question_text or snapshot_text,
            active_turns=active_turns,
            historical_turns=historical_turns,
            conversation_history=turn_window,
            primary_question_source=str(raw_context_bundle.get(\"primary_question_source\") or \"none\"),
            active_ask_key=active_ask_key,
            snapshot_hash=snapshot_hash,
            timestamp=datetime.utcnow(),
        )
""",
    "build snapshot v3",
)
text = replace_once(
    text,
    """    async def _compute_live_brain_plan_v3(
        self,
        *,
        brain_snapshot: BrainSnapshot,
        interview_config: dict[str, Any],
        force_stable: bool = False,
        immediate_safe_fallback: bool = False,
    ) -> tuple[BrainPlan, CompactEvidencePack]:
        can_use_cached_plan = (
            self._latest_brain_snapshot_v3 is not None
            and self._latest_brain_plan_v3 is not None
            and self._latest_brain_snapshot_v3.snapshot_hash == brain_snapshot.snapshot_hash
        )
        if can_use_cached_plan:
            cached_plan = self._normalize_live_brain_plan_for_active_route(self._latest_brain_plan_v3)
            cached_recovery_draft = str(self._latest_brain_recovery_draft_v3 or \"\")
            if force_stable and self._brain_plan_completeness_rank(cached_plan) < 3:
                can_use_cached_plan = False
            else:
                if force_stable and cached_plan.stability_state != \"stable\":
                    cached_plan = cached_plan.model_copy(update={\"stability_state\": \"stable\"})
                    self._latest_brain_plan_v3 = cached_plan
                    self._latest_stable_brain_plan_v3 = cached_plan
                    self._latest_stable_brain_recovery_draft_v3 = cached_recovery_draft
                evidence_pack = self._latest_compact_evidence_pack_v3 or self._live_evidence_packer_v3.pack(
                    plan=cached_plan,
                    interview_config=interview_config,
                )
                self._latest_compact_evidence_pack_v3 = evidence_pack
                self._latest_brain_recovery_draft_v3 = cached_recovery_draft
                return cached_plan, evidence_pack

        brain_started = self._mark_live_brain_started(signature=brain_snapshot.snapshot_hash)
        previous_plan = self._latest_brain_plan_v3
        try:
            if immediate_safe_fallback:
                plan = self._live_brain_service_v3.safe_plan(
                    snapshot=brain_snapshot,
                    interview_config=interview_config,
                    reasoning_summary=(
                        \"Live brain used immediate safe fallback at freeze to avoid extra silence latency.\"
                    ),
                )
                self._live_brain_last_llm_failure_kind = \"freeze_immediate_safe_fallback\"
            else:
                plan = await self._live_brain_service_v3.plan(
                    snapshot=brain_snapshot,
                    interview_config=interview_config,
                    previous_plan=previous_plan,
                )
                self._live_brain_last_llm_failure_kind = self._live_brain_service_v3.last_llm_failure_kind or \"\"
            recovery_draft = str(plan.draft_answer or \"\")
            reusable_stable_plan = self._latest_stable_brain_plan_v3
            if (
                reusable_stable_plan is not None
                and str(plan.plan_source or \"\").strip().lower() == \"safe_fallback\"
                and str(reusable_stable_plan.plan_source or \"\").strip().lower() == \"llm_fast\"
                and _is_cached_stable_brain_plan_compatible(
                    reusable_stable_plan,
                    plan,
                    brain_snapshot.snapshot_text,
                )
            ):
                plan = reusable_stable_plan.model_copy(
                    update={
                        \"utterance_id\": brain_snapshot.utterance_id,
                        \"revision_id\": brain_snapshot.revision_id,
                        \"snapshot_hash\": brain_snapshot.snapshot_hash,
                        \"generated_at\": brain_snapshot.timestamp,
                        \"stability_state\": \"stable\",
                        \"plan_source\": \"cached_stable\",
                        \"serve_mode\": (
                            \"finalize_from_draft\"
                            if str(reusable_stable_plan.draft_answer or \"\").strip()
                            else \"finalize_from_plan\"
                        ),
                    }
                )
                recovery_draft = str(self._latest_stable_brain_recovery_draft_v3 or recovery_draft)
            plan = self._normalize_live_brain_plan_for_active_route(plan)
            now = perf_counter()
            equivalent = LiveBrainService.plans_equivalent(previous_plan, plan)
            if equivalent:
                self._brain_plan_repeat_count_v3 += 1
            else:
                self._brain_plan_repeat_count_v3 = 1
                self._brain_plan_changed_at_v3 = now

            stability_state = \"draft\"
            if self._brain_plan_repeat_count_v3 >= 2:
                stability_state = \"stable_candidate\"
            quiet_sec = self._live_brain_service_v3.config.stable_quiet_ms / 1000.0
            if force_stable or (
                self._brain_plan_changed_at_v3 is not None
                and (now - self._brain_plan_changed_at_v3) >= quiet_sec
            ):
                stability_state = \"stable\"

            serve_mode = plan.serve_mode
            if serve_mode == \"direct_brain\":
                serve_mode = \"finalize_from_draft\" if str(plan.draft_answer or \"\").strip() else \"finalize_from_plan\"

            plan = plan.model_copy(
                update={
                    \"stability_state\": stability_state,
                    \"serve_mode\": \"finalize_from_plan\",
                }
            )
            evidence_pack = self._live_evidence_packer_v3.pack(
                plan=plan,
                interview_config=interview_config,
            )

            self._latest_brain_snapshot_v3 = brain_snapshot
            self._latest_brain_plan_v3 = plan
            self._latest_brain_recovery_draft_v3 = recovery_draft
            if plan.stability_state in {\"stable_candidate\", \"stable\"} and str(plan.plan_source or \"\").strip().lower() == \"llm_fast\":
                self._latest_stable_brain_plan_v3 = plan
                self._latest_stable_brain_recovery_draft_v3 = recovery_draft
            self._latest_compact_evidence_pack_v3 = evidence_pack
            self._latest_brain_plan_hash_v3 = self._live_brain_service_v3.plan_hash(plan)
            self._latest_brain_question_key_v3 = _normalize_live_question_text(
                _build_live_question_from_brain_plan(plan, brain_snapshot.snapshot_text)
            ).lower()
            self._mark_live_brain_finished(started_at=brain_started, status=\"completed\")
            return plan, evidence_pack
        except Exception as e:
            self._live_brain_last_llm_failure_kind = self._live_brain_service_v3.last_llm_failure_kind or \"\"
            self._mark_live_brain_finished(
                started_at=brain_started,
                status=\"failed\",
                failure_reason=type(e).__name__,
            )
            raise
""",
    """    async def _compute_live_brain_plan_v3(
        self,
        *,
        brain_snapshot: BrainSnapshot,
        interview_config: dict[str, Any],
        force_stable: bool = False,
        immediate_safe_fallback: bool = False,
    ) -> tuple[BrainPlan, CompactEvidencePack]:
        del immediate_safe_fallback
        can_use_cached_plan = (
            self._latest_brain_snapshot_v3 is not None
            and self._latest_brain_plan_v3 is not None
            and self._latest_brain_snapshot_v3.snapshot_hash == brain_snapshot.snapshot_hash
            and str(self._latest_brain_plan_v3.plan_source or \"\").strip().lower() == \"llm_fast\"
        )
        if can_use_cached_plan:
            cached_plan = self._normalize_live_brain_plan_for_active_route(self._latest_brain_plan_v3)
            if not force_stable or self._brain_plan_completeness_rank(cached_plan) >= 3:
                evidence_pack = self._latest_compact_evidence_pack_v3 or self._live_evidence_packer_v3.pack(
                    plan=cached_plan,
                    interview_config=interview_config,
                )
                self._latest_compact_evidence_pack_v3 = evidence_pack
                return cached_plan, evidence_pack

        brain_started = self._mark_live_brain_started(signature=brain_snapshot.snapshot_hash)
        previous_plan = (
            self._latest_brain_plan_v3
            if self._latest_brain_plan_v3 is not None
            and str(self._latest_brain_plan_v3.plan_source or \"\").strip().lower() == \"llm_fast\"
            else None
        )
        try:
            plan, llm_failure_kind = await self._live_brain_service_v3._plan_with_llm(
                snapshot=brain_snapshot,
                interview_config=interview_config,
                previous_plan=previous_plan,
            )
            self._live_brain_last_llm_failure_kind = llm_failure_kind or \"\"
            if plan is None:
                raise RuntimeError(f\"live_brain_llm_only_failed:{llm_failure_kind or 'unknown'}\")

            plan = plan.model_copy(
                update={
                    \"generated_at\": brain_snapshot.timestamp,
                    \"plan_source\": \"llm_fast\",
                    \"reasoning_summary\": plan.reasoning_summary
                    or \"Live brain plan generated from the latest interviewer snapshot.\",
                }
            )
            recovery_draft = str(plan.draft_answer or \"\")
            plan = self._normalize_live_brain_plan_for_active_route(plan)
            now = perf_counter()
            equivalent = LiveBrainService.plans_equivalent(previous_plan, plan)
            if equivalent:
                self._brain_plan_repeat_count_v3 += 1
            else:
                self._brain_plan_repeat_count_v3 = 1
                self._brain_plan_changed_at_v3 = now

            stability_state = \"draft\"
            if self._brain_plan_repeat_count_v3 >= 2:
                stability_state = \"stable_candidate\"
            quiet_sec = self._live_brain_service_v3.config.stable_quiet_ms / 1000.0
            if force_stable or (
                self._brain_plan_changed_at_v3 is not None
                and (now - self._brain_plan_changed_at_v3) >= quiet_sec
            ):
                stability_state = \"stable\"

            plan = plan.model_copy(
                update={
                    \"stability_state\": stability_state,
                    \"serve_mode\": \"finalize_from_plan\",
                }
            )
            evidence_pack = self._live_evidence_packer_v3.pack(
                plan=plan,
                interview_config=interview_config,
            )

            self._latest_brain_snapshot_v3 = brain_snapshot
            self._latest_brain_plan_v3 = plan
            self._latest_brain_recovery_draft_v3 = recovery_draft
            if plan.stability_state in {\"stable_candidate\", \"stable\"}:
                self._latest_stable_brain_plan_v3 = plan
                self._latest_stable_brain_recovery_draft_v3 = recovery_draft
            self._latest_compact_evidence_pack_v3 = evidence_pack
            self._latest_brain_plan_hash_v3 = self._live_brain_service_v3.plan_hash(plan)
            self._latest_brain_question_key_v3 = _normalize_live_question_text(
                _build_live_question_from_brain_plan(plan, brain_snapshot.snapshot_text)
            ).lower()
            self._mark_live_brain_finished(started_at=brain_started, status=\"completed\")
            return plan, evidence_pack
        except Exception as e:
            self._live_brain_last_llm_failure_kind = self._live_brain_service_v3.last_llm_failure_kind or self._live_brain_last_llm_failure_kind or \"\"
            self._mark_live_brain_finished(
                started_at=brain_started,
                status=\"failed\",
                failure_reason=type(e).__name__,
            )
            raise
""",
    "compute live brain plan",
)
text = replace_once(
    text,
    """        raw_turn_window, turn_window, raw_context_bundle = self._resolve_live_active_context_bundle(limit=5)
        if not raw_turn_window or not turn_window:
            return None
        brain_snapshot = self._build_live_brain_snapshot_v3(limit=5, turn_window=turn_window)
        if brain_snapshot is None:
            return None

        prior_snapshot = self._latest_brain_snapshot_v3
        cache_hit = bool(
            prior_snapshot is not None and prior_snapshot.snapshot_hash == brain_snapshot.snapshot_hash
        )
        brain_refresh_wait_ms = 0
        if (
            not self._live_brain_plan_ready_for_snapshot_v3(brain_snapshot=brain_snapshot)
            and self._live_brain_refresh_task_v3 is not None
            and not self._live_brain_refresh_task_v3.done()
            and self._live_brain_refresh_active_signature_v3 == brain_snapshot.snapshot_hash
        ):
            brain_refresh_wait_ms = await self._await_live_brain_v3_refresh(
                snapshot_hash=brain_snapshot.snapshot_hash,
                timeout_sec=self._live_brain_freeze_wait_grace_sec,
            )
            prior_snapshot = self._latest_brain_snapshot_v3
            cache_hit = bool(
                prior_snapshot is not None and prior_snapshot.snapshot_hash == brain_snapshot.snapshot_hash
            )
        self._brain_refresh_waited_at_freeze_ms = brain_refresh_wait_ms
        use_immediate_safe_fallback = not self._live_brain_plan_ready_for_snapshot_v3(
            brain_snapshot=brain_snapshot,
        )
        self._brain_force_stable_at_freeze = use_immediate_safe_fallback
        self._brain_immediate_safe_fallback_at_freeze = use_immediate_safe_fallback
        brain_plan, evidence_pack = await self._compute_live_brain_plan_v3(
            brain_snapshot=brain_snapshot,
            interview_config=interview_config,
            force_stable=True,
            immediate_safe_fallback=use_immediate_safe_fallback,
        )
""",
    """        raw_turn_window, turn_window, raw_context_bundle = self._resolve_live_active_context_bundle(limit=5)
        if not raw_turn_window or not turn_window:
            return None
        brain_snapshot = self._build_live_brain_snapshot_v3(
            limit=5,
            turn_window=turn_window,
            raw_context_bundle=raw_context_bundle,
        )
        if brain_snapshot is None:
            return None

        prior_snapshot = self._latest_brain_snapshot_v3
        cache_hit = bool(
            prior_snapshot is not None and prior_snapshot.snapshot_hash == brain_snapshot.snapshot_hash
        )
        brain_refresh_wait_ms = 0
        if (
            not self._live_brain_plan_ready_for_snapshot_v3(brain_snapshot=brain_snapshot)
            and self._live_brain_refresh_task_v3 is not None
            and not self._live_brain_refresh_task_v3.done()
            and self._live_brain_refresh_active_signature_v3 == brain_snapshot.snapshot_hash
        ):
            brain_refresh_wait_ms = await self._await_live_brain_v3_refresh(
                snapshot_hash=brain_snapshot.snapshot_hash,
                timeout_sec=self._live_brain_freeze_wait_grace_sec,
            )
            prior_snapshot = self._latest_brain_snapshot_v3
            cache_hit = bool(
                prior_snapshot is not None and prior_snapshot.snapshot_hash == brain_snapshot.snapshot_hash
            )
        self._brain_refresh_waited_at_freeze_ms = brain_refresh_wait_ms
        self._brain_force_stable_at_freeze = False
        self._brain_immediate_safe_fallback_at_freeze = False
        brain_plan, evidence_pack = await self._compute_live_brain_plan_v3(
            brain_snapshot=brain_snapshot,
            interview_config=interview_config,
            force_stable=True,
            immediate_safe_fallback=False,
        )
""",
    "freeze snapshot build",
)
server.write_text(text)


text = brain.read_text()
text = replace_once(
    text,
    """        if previous_source not in {\"llm_fast\", \"cached_stable\"}:
            return None
""",
    """        if previous_source != \"llm_fast\":
            return None
""",
    "carry forward source gate",
)
text = replace_once(
    text,
    """        (
            safe_raw_detected,
            safe_accepted,
            safe_dropped,
            safe_completeness,
            safe_clause_classifications,
            safe_supporting_interviewer_context,
        ) = self._extract_safe_candidates(
            snapshot.snapshot_text
        )
""",
    """        active_question_text = self._normalize_text(snapshot.active_question_text or snapshot.snapshot_text)
        (
            safe_raw_detected,
            safe_accepted,
            safe_dropped,
            safe_completeness,
            safe_clause_classifications,
            safe_supporting_interviewer_context,
        ) = self._extract_safe_candidates(
            active_question_text
        )
        historical_supporting_context = self._normalize_unique_strings(
            [
                self._normalize_text(turn.get(\"text\"))
                for turn in list(snapshot.historical_turns or [])
                if self._normalize_text(turn.get(\"text\"))
            ]
        )
""",
    "llm normalize safe candidates from active block",
)
text = replace_once(
    text,
    """        ordered_asks, raw_detected_asks, dropped_noise_clauses, resolved_question = self._prefer_stronger_safe_asks(
            ordered_asks=ordered_asks,
            raw_detected_asks=raw_detected_asks,
            dropped_noise_clauses=dropped_noise_clauses,
            resolved_question=resolved_question,
            safe_accepted=safe_accepted,
            safe_raw_detected=safe_raw_detected,
            safe_dropped=safe_dropped,
        )
""",
    """        ordered_asks = [
            ask
            for ask in self._normalize_unique_strings(ordered_asks)
            if self._ask_is_grounded_in_active_question(ask, active_question_text)
        ]
        raw_detected_asks = [
            ask
            for ask in self._normalize_unique_strings(raw_detected_asks)
            if self._ask_is_grounded_in_active_question(ask, active_question_text)
        ]
        dropped_noise_clauses = self._normalize_unique_strings(dropped_noise_clauses)
""",
    "remove stronger safe ask override",
)
text = replace_once(
    text,
    """            context_focus = self._normalize_unique_strings(safe_supporting_interviewer_context[:4])
""",
    """            context_focus = self._normalize_unique_strings(
                [*historical_supporting_context, *safe_supporting_interviewer_context]
            )[:4]
""",
    "context focus from supporting context",
)
for label in [
    "ask intents snapshot text",
    "interviewer need snapshot text",
    "response requirement snapshot text",
    "compatibility snapshot text",
]:
    text = replace_once(
        text,
        "            snapshot_text=snapshot.snapshot_text,\\n",
        "            snapshot_text=active_question_text or snapshot.snapshot_text,\\n",
        label,
    )
text = replace_once(
    text,
    """            supporting_interviewer_context=safe_supporting_interviewer_context[:6],
""",
    """            supporting_interviewer_context=self._normalize_unique_strings(
                [*historical_supporting_context, *safe_supporting_interviewer_context]
            )[:6],
""",
    "plan supporting context",
)
text = replace_once(
    text,
    """                or (snapshot.snapshot_text if question_completeness == \"complete\" else \"\")
""",
    """                or (active_question_text if question_completeness == \"complete\" else \"\")
""",
    "resolved question fallback",
)
text = replace_once(
    text,
    """CONSOLIDATED INTERVIEWER HISTORY:
{snapshot.snapshot_text}

RECENT CONVERSATION HISTORY:
{self._format_history(snapshot.conversation_history[-5:])}
""",
    """ACTIVE ASK BLOCK:
{snapshot.active_question_text or snapshot.snapshot_text}

SUPPORTING INTERVIEWER CONTEXT:
{self._format_history(snapshot.historical_turns) if list(snapshot.historical_turns or []) else \"None\"}

RECENT CONVERSATION HISTORY:
{self._format_history(snapshot.conversation_history[-5:])}
""",
    "prompt split blocks",
)
text = replace_once(
    text,
    """- Ignore filler, preamble, repeated fragments, and interviewer self-commentary unless they materially shape how the answer should be framed.
""",
    """- Ignore filler, preamble, repeated fragments, and interviewer self-commentary unless they materially shape how the answer should be framed.
- ACTIVE ASK BLOCK is the only source allowed to create literal_question and asks. SUPPORTING INTERVIEWER CONTEXT may shape interviewer_need, context_focus, and response_requirement.context_to_weave, but it must not create new asks.
- If the active block contains a semantically clear ask plus a repeated truncated tail, keep the clear ask and treat the tail as repetition rather than a new incomplete question.
""",
    "prompt rules block 1",
)
text = replace_once(
    text,
    """- Treat prior turns as interviewer context when they define the problem, constraints, success criteria, leadership expectations, technical environment, or why the current question matters.
""",
    """- Treat prior turns as interviewer context when they define the problem, constraints, success criteria, leadership expectations, technical environment, or why the current question matters.
- Do not copy SUPPORTING INTERVIEWER CONTEXT into asks unless that same ask is explicitly present again in the ACTIVE ASK BLOCK.
""",
    "prompt rules block 2",
)
helper = """    def _ask_is_grounded_in_active_question(self, ask: str, active_question_text: str) -> bool:
        normalized_ask = self._normalize_text(ask)
        normalized_active = self._normalize_text(active_question_text)
        if not normalized_ask:
            return False
        if not normalized_active:
            return True

        ask_key = normalized_ask.rstrip(\"?.!\").lower()
        active_lower = normalized_active.lower()
        if ask_key and ask_key in active_lower:
            return True

        active_clauses = self._split_candidate_clauses(normalized_active)
        return any(
            self._asks_semantically_overlap(normalized_ask, clause)
            for clause in active_clauses
        )

"""
anchor = "    def _prefer_stronger_safe_asks(\\n"
if helper not in text:
    idx = text.find(anchor)
    if idx == -1:
        raise SystemExit("missing helper anchor")
    text = text[:idx] + helper + text[idx:]
brain.write_text(text)


text = finalizer.read_text()
text = text.replace('{\"llm_fast\", \"cached_stable\"}', '{\"llm_fast\"}')
finalizer.write_text(text)

print("patched")
