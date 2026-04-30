from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import MovieInfo, SubtitleCandidate, now_iso


class AppStorage:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                create table if not exists task_runs (
                    id integer primary key autoincrement,
                    started_at text not null,
                    finished_at text,
                    year integer,
                    limit_count integer,
                    status text not null,
                    result_json text not null default '{}'
                );

                create table if not exists movies (
                    movie_id text primary key,
                    tmdb_id integer,
                    title text,
                    original_title text,
                    title_zh text,
                    year integer,
                    rating real,
                    vote_count integer,
                    release_date text,
                    raw_json text,
                    updated_at text not null
                );

                create table if not exists subtitle_candidates (
                    provider text not null,
                    provider_subtitle_id text not null,
                    movie_id text not null,
                    subtitle_title text,
                    subtitle_format text,
                    language_type text,
                    download_count integer,
                    total_score real,
                    raw_json text,
                    updated_at text not null,
                    primary key (provider, provider_subtitle_id, movie_id)
                );
                """
            )

    def create_task_run(self, year: int, limit: int) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into task_runs (started_at, year, limit_count, status)
                values (?, ?, ?, ?)
                """,
                (now_iso(), year, limit, "running"),
            )
            return int(cursor.lastrowid)

    def finish_task_run(self, run_id: int, status: str, result: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                update task_runs
                set finished_at = ?, status = ?, result_json = ?
                where id = ?
                """,
                (now_iso(), status, json.dumps(result, ensure_ascii=False), run_id),
            )

    def list_task_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select id, started_at, finished_at, year, limit_count, status, result_json
                from task_runs
                order by id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["result"] = json.loads(item.pop("result_json") or "{}")
            except json.JSONDecodeError:
                item["result"] = {}
            return_key_map = {"limit_count": "limit"}
            for old, new in return_key_map.items():
                item[new] = item.pop(old)
            result.append(item)
        return result

    def clear_task_runs(self) -> None:
        with self._connect() as connection:
            connection.execute("delete from task_runs")

    def save_movie(self, movie: MovieInfo) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into movies (
                    movie_id, tmdb_id, title, original_title, title_zh, year, rating,
                    vote_count, release_date, raw_json, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(movie_id) do update set
                    tmdb_id = excluded.tmdb_id,
                    title = excluded.title,
                    original_title = excluded.original_title,
                    title_zh = excluded.title_zh,
                    year = excluded.year,
                    rating = excluded.rating,
                    vote_count = excluded.vote_count,
                    release_date = excluded.release_date,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    movie.movie_id,
                    movie.tmdb_id,
                    movie.title,
                    movie.original_title,
                    movie.title_zh,
                    movie.year,
                    movie.rating,
                    movie.vote_count,
                    movie.release_date,
                    json.dumps(movie.raw, ensure_ascii=False),
                    now_iso(),
                ),
            )

    def save_candidate(self, candidate: SubtitleCandidate) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into subtitle_candidates (
                    provider, provider_subtitle_id, movie_id, subtitle_title, subtitle_format,
                    language_type, download_count, total_score, raw_json, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(provider, provider_subtitle_id, movie_id) do update set
                    subtitle_title = excluded.subtitle_title,
                    subtitle_format = excluded.subtitle_format,
                    language_type = excluded.language_type,
                    download_count = excluded.download_count,
                    total_score = excluded.total_score,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    candidate.provider,
                    candidate.provider_subtitle_id,
                    candidate.movie_id,
                    candidate.subtitle_title,
                    candidate.subtitle_format,
                    candidate.language_type,
                    candidate.download_count,
                    candidate.total_score,
                    json.dumps(candidate.to_export_dict(), ensure_ascii=False),
                    now_iso(),
                ),
            )
