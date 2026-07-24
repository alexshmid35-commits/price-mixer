"""Cached XLSX delivery built from the shared revision-aware export runtime."""

from __future__ import annotations

from io import BytesIO


class ExportDeliveryRuntime:
    def __init__(self, *, export_runtime, dataframe_to_export_dataframe):
        self.export_runtime = export_runtime
        self.dataframe_to_export_dataframe = dataframe_to_export_dataframe

    def xlsx(self, session_dir, settings, *, revision_token):
        return self.export_runtime.build_artifact(
            session_dir,
            settings,
            revision_token=revision_token,
            artifact_key="fixed-layout-xlsx-v1",
            builder=self._render_xlsx,
        )

    def _render_xlsx(self, dataframe):
        output = BytesIO()
        export_frame = self.dataframe_to_export_dataframe(dataframe)
        export_frame.to_excel(
            output,
            index=False,
            float_format="%.2f",
        )
        return output.getvalue()
