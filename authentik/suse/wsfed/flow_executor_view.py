# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""authentik multi-stage authentication engine"""

from django.http import HttpResponse

from authentik.flows.views.executor import (
    FlowExecutorView as BaseFlowExecutorView,
)


class FlowExecutorView(BaseFlowExecutorView):
    completed = False

    def _flow_done(self) -> HttpResponse:
        self.completed = True
        return super()._flow_done()
