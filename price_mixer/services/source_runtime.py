"""Runtime facade for API source fetch and processing routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from price_mixer.services import api_sources


@dataclass(frozen=True)
class SourceRuntime:
    session_obj: object
    load_settings: Callable[[], dict]
    fetch_worker: Callable[[str, str], None]
    thread_factory: Callable[[Callable[[], None]], None]
    get_history: Callable[..., list]
    process_supplier_files: Callable[[list[dict]], dict]
    finalize_processed_session: Callable[[str, str, str], None]
    append_history: Callable[[dict], None]
    redirect_for_session: Callable[[str], str]
    enqueue_fetch: Callable[[str, str], None] | None = None

    def client_key(self):
        return api_sources.get_api_source_status_key(self.session_obj)

    def fetch_start(self, payload):
        return api_sources.source_fetch_start_payload(
            payload,
            client_key=self.client_key(),
            settings=self.load_settings(),
            start_worker=(
                self.enqueue_fetch
                if self.enqueue_fetch is not None
                else lambda source_key, key: self.thread_factory(
                    lambda: self.fetch_worker(source_key, key)
                )
            ),
        )

    def fetch_status(self, source_key=""):
        return api_sources.source_fetch_status_payload(
            source_key,
            client_key=self.client_key(),
            settings=self.load_settings(),
            history=self.get_history(limit=20),
        )

    def process(self, payload):
        return api_sources.process_source_payload(
            payload,
            client_key=self.client_key(),
            process_supplier_files=self.process_supplier_files,
            finalize_processed_session=self.finalize_processed_session,
            append_history=self.append_history,
            redirect_for_session=self.redirect_for_session,
        )

    def process_batch(self, payload):
        client_key = self.client_key()
        return api_sources.process_source_batch_payload(
            payload,
            client_key=client_key,
            client_state=api_sources.get_client_source_state(client_key),
            process_supplier_files=self.process_supplier_files,
            finalize_processed_session=self.finalize_processed_session,
            append_history=self.append_history,
            redirect_for_session=self.redirect_for_session,
        )
