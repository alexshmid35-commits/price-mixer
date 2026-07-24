import zipfile
from io import BytesIO

import pandas as pd

from price_mixer.services.export_delivery import ExportDeliveryRuntime


class ExportRuntimeStub:
    def build_artifact(
        self,
        session_dir,
        settings,
        *,
        revision_token,
        artifact_key,
        builder,
    ):
        frame = pd.DataFrame({"Название": ["SSD"], "Цена": [10.5]})
        return builder(frame), "price.xlsx"


def test_export_delivery_builds_valid_xlsx_bytes():
    delivery = ExportDeliveryRuntime(
        export_runtime=ExportRuntimeStub(),
        dataframe_to_export_dataframe=lambda frame: frame,
    )

    payload, name = delivery.xlsx(
        "session",
        {},
        revision_token=("sql", 1),
    )

    assert name == "price.xlsx"
    assert zipfile.is_zipfile(BytesIO(payload))
