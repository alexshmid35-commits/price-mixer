import onliner_to_sheets as parser


class FakeSheet:
    row_count = 8

    def __init__(self):
        self.calls = []

    def batch_get(self, ranges):
        self.calls.append(ranges)
        start_row = int(ranges[0].split(":", 1)[0][1:])
        if start_row == 2:
            return (
                [["Category"], ["Category"], ["Category"]],
                [["101", "https://example/101"], ["N/A", "https://example/no-id"], ["102"]],
            )
        if start_row == 5:
            return ([[], ["Category"]], [[], ["103", "https://example/103"]])
        return ([], [])


def test_existing_identities_are_loaded_in_bounded_chunks():
    sheet = FakeSheet()

    ids, urls, next_row = parser.get_existing_identity_sets(sheet, chunk_rows=3)

    assert ids == {"101", "102", "103"}
    assert urls == {
        "https://example/101",
        "https://example/no-id",
        "https://example/103",
    }
    assert next_row == 7
    assert sheet.calls == [
        ["A2:A4", "E2:F4"],
        ["A5:A7", "E5:F7"],
        ["A8:A8", "E8:F8"],
    ]
