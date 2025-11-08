import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

os.environ.setdefault("SUPABASE_URL", "http://test.supabase.local")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")


def _parse_iso_to_naive(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class FakeQuery:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows
        self._filters: List[tuple] = []
        self._count_mode: Optional[str] = None

    def select(self, _columns: str, count: Optional[str] = None):
        self._count_mode = count
        return self

    def gte(self, field: str, value: str):
        self._filters.append(("gte", field, value))
        return self

    def lte(self, field: str, value: str):
        self._filters.append(("lte", field, value))
        return self

    def eq(self, field: str, value: Any):
        self._filters.append(("eq", field, value))
        return self

    def _match(self, row: Dict[str, Any]) -> bool:
        for op, field, value in self._filters:
            if op == "eq":
                if row.get(field) != value:
                    return False
            else:
                row_ts = _parse_iso_to_naive(row.get(field))
                cmp_ts = _parse_iso_to_naive(value)
                if row_ts is None or cmp_ts is None:
                    return False
                if op == "gte" and row_ts < cmp_ts:
                    return False
                if op == "lte" and row_ts > cmp_ts:
                    return False
        return True

    def execute(self):
        matched = [row for row in self._rows if self._match(row)]
        if self._count_mode == "exact":
            return SimpleNamespace(data=matched, count=len(matched))
        return SimpleNamespace(data=matched, count=None)


class FakeSupabase:
    def __init__(self, data: Dict[str, List[Dict[str, Any]]]):
        self._data = data

    def table(self, name: str):
        rows = self._data.get(name, [])
        return FakeQuery(rows)


SAMPLE_DATA: Dict[str, List[Dict[str, Any]]] = {
    "fact_leads": [
        {
            "id": 1,
            "event_time": "2024-08-10T08:30:00+00:00",
            "province_code": "110000",
            "province_name": "北京市",
            "city_code": "110100",
            "city_name": "北京市",
            "district_code": "110101",
            "district_name": "东城区",
            "country_iso3": None,
        },
        {
            "id": 2,
            "event_time": "2024-08-09T09:00:00+00:00",
            "province_code": "110000",
            "province_name": "北京市",
            "city_code": "110100",
            "city_name": "北京市",
            "district_code": "110101",
            "district_name": "东城区",
            "country_iso3": None,
        },
        {
            "id": 3,
            "event_time": "2024-08-10T11:00:00+00:00",
            "province_code": "310000",
            "province_name": "上海市",
            "city_code": "310100",
            "city_name": "上海市",
            "district_code": "310101",
            "district_name": "黄浦区",
            "country_iso3": None,
        },
        {
            "id": 4,
            "event_time": "2024-08-08T10:00:00+00:00",
            "province_code": "110000",
            "province_name": "北京市",
            "city_code": "110100",
            "city_name": "北京市",
            "district_code": "110102",
            "district_name": "西城区",
            "country_iso3": None,
        },
        {
            "id": 5,
            "event_time": "2024-08-07T14:00:00+00:00",
            "province_code": "110000",
            "province_name": "北京市",
            "city_code": "110100",
            "city_name": "北京市",
            "district_code": "110103",
            "district_name": "崇文区",
            "country_iso3": None,
        },
        {
            "id": 6,
            "event_time": "2024-08-05T14:00:00+00:00",
            "province_code": "110000",
            "province_name": "北京市",
            "city_code": "110100",
            "city_name": "北京市",
            "district_code": "110104",
            "district_name": "宣武区",
            "country_iso3": None,
        },
    ],
    "fact_news": [
        {
            "id": 10,
            "publish_time": "2024-08-10T03:00:00+00:00",
            "province_code": "110000",
            "province_name": "北京市",
            "city_code": "110100",
            "city_name": "北京市",
            "district_code": "110101",
            "district_name": "东城区",
            "country_iso3": None,
        },
        {
            "id": 11,
            "publish_time": "2024-08-08T07:00:00+00:00",
            "province_code": "310000",
            "province_name": "上海市",
            "city_code": "310100",
            "city_name": "上海市",
            "district_code": "310101",
            "district_name": "黄浦区",
            "country_iso3": None,
        },
    ],
    "fact_tenders": [
        {
            "id": 12,
            "publish_date": "2024-08-10T09:15:00+00:00",
            "province_code": "110000",
            "province_name": "北京市",
            "city_code": "110100",
            "city_name": "北京市",
            "district_code": "110101",
            "district_name": "东城区",
            "country_iso3": None,
        }
    ],
    "fact_policies": [
        {
            "id": 14,
            "publish_date": "2024-08-09T05:00:00+00:00",
            "province_code": "110000",
            "province_name": "北京市",
            "city_code": "110100",
            "city_name": "北京市",
            "district_code": "110101",
            "district_name": "东城区",
            "country_iso3": None,
        }
    ],
}


class DataboardMapBlueprintTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as flask_app
        from backend_api import databoard_map_bp

        cls.map_bp = databoard_map_bp
        cls.map_bp.sb = FakeSupabase(SAMPLE_DATA)

        def fake_group_count(table, time_field, group_field, start, end, extra_filters=None):
            extra_filters = extra_filters or {}
            rows = SAMPLE_DATA.get(table, [])
            result: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                ts = _parse_iso_to_naive(row.get(time_field))
                if ts is None or ts < start or ts > end:
                    continue
                if any(row.get(k) != v for k, v in extra_filters.items()):
                    continue
                code = row.get(group_field)
                if not code:
                    continue
                bucket = result.setdefault(code, {"count": 0})
                bucket["count"] += 1
                name_field = None
                if group_field == cls.map_bp.WORLD_REGION_CODE_FIELD:
                    name_field = cls.map_bp.WORLD_REGION_NAME_FIELD
                else:
                    for level, field in cls.map_bp.CN_REGION_FIELDS.items():
                        if field == group_field:
                            name_field = cls.map_bp.CN_REGION_NAME_FIELDS.get(level)
                            break
                if name_field and not bucket.get("name"):
                    name_value = row.get(name_field)
                    if name_value:
                        bucket["name"] = name_value
            return result

        cls.map_bp._group_count = fake_group_count
        cls.client = flask_app.app.test_client()

    def test_get_map_data_province_all(self):
        resp = self.client.get(
            "/api/databoard/map/data",
            query_string={"level": "province", "date": "2024-08-10", "timeRange": "day", "type": "all"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload["code"], 20000)
        stats = payload["data"]["statistics"]
        self.assertEqual(stats[0]["code"], "110000")
        self.assertEqual(stats[0]["value"], 3)
        self.assertEqual(stats[0]["leads"], 1)
        self.assertEqual(stats[0]["tenders"], 1)
        self.assertEqual(stats[0]["news"], 1)
        self.assertEqual(payload["data"]["summary"]["total"], 4)

    def test_get_region_detail_province(self):
        resp = self.client.get(
            "/api/databoard/map/region",
            query_string={"region": "110000", "date": "2024-08-10", "timeRange": "day", "type": "all"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload["code"], 20000)
        region_info = payload["data"]["region"]
        self.assertEqual(region_info["code"], "110000")
        self.assertEqual(region_info["level"], "province")
        self.assertEqual(payload["data"]["statistics"][0]["value"], 3)
        self.assertTrue(any(item["code"] == "110100" for item in payload["data"]["subRegions"]))

    def test_get_map_summary(self):
        resp = self.client.get(
            "/api/databoard/map/summary",
            query_string={"date": "2024-08-10", "timeRange": "day", "type": "all"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload["code"], 20000)
        body = payload["data"]
        self.assertEqual(body["total"], 4)
        self.assertEqual(body["byType"]["leads"], 2)
        self.assertEqual(body["byType"]["tenders"], 1)
        self.assertEqual(body["byType"]["news"], 1)

    def test_get_region_trend_day(self):
        resp = self.client.get(
            "/api/databoard/map/trend",
            query_string={"region": "110000", "date": "2024-08-10", "period": "day", "type": "leads"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload["code"], 20000)
        trend = payload["data"]["trendData"]
        self.assertEqual(len(trend), 7)
        self.assertEqual(trend[-1]["date"], "2024-08-10")
        self.assertEqual(trend[-1]["value"], 1)
        self.assertEqual(trend[-1]["change"], 0.0)


if __name__ == "__main__":
    unittest.main()
