# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""Flows Planner"""

from copy import copy
from typing import Any

from django.http import HttpRequest
from sentry_sdk import start_span
from sentry_sdk.tracing import Span

from authentik.core.models import User
from authentik.flows.apps import HIST_FLOWS_PLAN_TIME
from authentik.flows.markers import ReevaluateMarker, StageMarker
from authentik.flows.models import (
    Flow,
    FlowStageBinding,
    Stage,
)
from authentik.flows.planner import (
    FlowPlan as BaseFlowPlan,
)
from authentik.flows.planner import (
    FlowPlanner as BaseFlowPlanner,
)
from authentik.policies.engine import PolicyEngine
from authentik.suse.wsfed.flow_executor_view import (
    FlowExecutorView,
)


class FlowPlan(BaseFlowPlan):
    def run_until_completion(self, request: HttpRequest, flow: Flow):
        """
        runs a plan until completion, it assumes that the provided request
        contains all the data needed across all stages.
        """
        # Freeze the request body in memory
        _ = request.body

        req = HttpRequest()
        req.method = "GET"
        req.META = request.META
        req.request_id = request.request_id
        req.session = request.session
        req.tenant = request.tenant
        req.brand = request.brand
        req.user = request.user

        for _ in self.bindings:
            # Reuse the request body across all fake requests
            if request._stream.seekable():
                request._stream.seek(0)

            # Satisfy current stage [returns a redirect]
            post_req = copy(request)
            temp_exec = FlowExecutorView(flow=flow, request=post_req, plan=self)
            temp_exec.setup(post_req, flow.slug)
            temp_exec.dispatch(post_req, flow.slug)

            # Transition to next stage [returns the component]
            temp_exec = FlowExecutorView(flow=flow, request=req, plan=self)
            temp_exec.setup(req, flow.slug)
            temp_exec.dispatch(req, flow.slug)

        temp_exec = FlowExecutorView(flow=flow, request=req, plan=self)
        temp_exec.setup(req, flow.slug)
        temp_exec.dispatch(req, flow.slug)
        if temp_exec.completed:
            return True

        return False


class FlowPlanner(BaseFlowPlanner):

    def _build_plan(
        self,
        user: User,
        request: HttpRequest,
        default_context: dict[str, Any] | None,
    ) -> FlowPlan:
        """Build flow plan by checking each stage in their respective
        order and checking the applied policies"""
        with (
            start_span(
                op="authentik.flow.planner.build_plan",
                name=self.flow.slug,
            ) as span,
            HIST_FLOWS_PLAN_TIME.labels(flow_slug=self.flow.slug).time(),
        ):
            span: Span
            span.set_data("flow", self.flow)
            span.set_data("user", user)
            span.set_data("request", request)

            plan = FlowPlan(flow_pk=self.flow.pk.hex)
            if default_context:
                plan.context = default_context
            # Check Flow policies
            bindings = list(
                FlowStageBinding.objects.filter(target__pk=self.flow.pk).order_by("order")
            )
            stages = Stage.objects.filter(flowstagebinding__in=[binding.pk for binding in bindings])
            for binding in bindings:
                binding: FlowStageBinding
                stage = [stage for stage in stages if stage.pk == binding.stage_id][0]
                marker = StageMarker()
                if binding.evaluate_on_plan:
                    self._logger.debug(
                        "f(plan): evaluating on plan",
                        stage=stage,
                    )
                    engine = PolicyEngine(binding, user, request)
                    engine.use_cache = self.use_cache
                    engine.request.context["flow_plan"] = plan
                    engine.request.context.update(plan.context)
                    engine.build()
                    if engine.passing:
                        self._logger.debug(
                            "f(plan): stage passing",
                            stage=stage,
                        )
                    else:
                        stage = None
                else:
                    self._logger.debug(
                        "f(plan): not evaluating on plan",
                        stage=stage,
                    )
                if binding.re_evaluate_policies and stage:
                    self._logger.debug(
                        "f(plan): stage has re-evaluate marker",
                        stage=stage,
                    )
                    marker = ReevaluateMarker(binding=binding)
                if stage:
                    plan.append(binding, marker)
        self._logger.debug(
            "f(plan): finished building",
        )
        return plan
