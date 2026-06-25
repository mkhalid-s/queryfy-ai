"""
Tests for sampling bias detection.
"""
import pytest
from app.services.tools.query_tools import detect_data_characteristics


class TestDataCharacteristics:
    """Test data characteristics detection"""

    def test_time_series_detection(self):
        """Should detect time-series columns"""
        columns = ["id", "user_name", "created_at", "order_date"]
        rows = [
            {"id": i, "user_name": f"user{i}", "created_at": "2024-01-01", "order_date": "2024-01-01"}
            for i in range(100)
        ]

        result = detect_data_characteristics(columns, rows)

        assert result["has_time_series"]
        assert not result["sampling_appropriate"]
        assert any("time-series" in w.lower() or "created_at" in w or "order_date" in w
                  for w in result["warnings"])

    def test_sequential_id_detection(self):
        """Should detect sequential ID columns"""
        columns = ["order_id", "product_name", "amount"]
        rows = [
            {"order_id": i, "product_name": f"prod{i}", "amount": 100}
            for i in range(1, 101)  # Sequential IDs 1-100
        ]

        result = detect_data_characteristics(columns, rows)

        assert result["has_id_sequence"]
        assert not result["sampling_appropriate"]
        assert any("sequential" in w.lower() for w in result["warnings"])

    def test_outlier_risk_detection(self):
        """Should detect high variance columns"""
        columns = ["id", "order_total"]
        # Most orders $10-100, few orders $10,000+
        rows = [{"id": i, "order_total": 50} for i in range(95)]  # 95% low value
        rows += [{"id": i, "order_total": 10000} for i in range(95, 100)]  # 5% high value

        result = detect_data_characteristics(columns, rows)

        assert result["has_outliers_risk"]
        assert any("variance" in w.lower() for w in result["warnings"])

    def test_normal_data_no_warnings(self):
        """Normal data should have no warnings"""
        columns = ["product_id", "product_name", "price"]
        rows = [
            {"product_id": f"P{i:04d}", "product_name": f"Product {i}", "price": 100 + i}
            for i in range(100)
        ]

        result = detect_data_characteristics(columns, rows)

        assert not result["has_time_series"]
        assert not result["has_id_sequence"]
        assert not result["has_outliers_risk"]
        assert result["sampling_appropriate"]
        assert len(result["warnings"]) == 0

    def test_mixed_characteristics(self):
        """Should detect multiple characteristics"""
        columns = ["order_id", "customer_name", "created_at", "amount"]
        rows = [
            {"order_id": i, "customer_name": f"Customer {i}", "created_at": "2024-01-01", "amount": 100}
            for i in range(1, 101)
        ]

        result = detect_data_characteristics(columns, rows)

        # Should detect both time-series and sequential ID
        assert result["has_time_series"]
        assert result["has_id_sequence"]
        assert not result["sampling_appropriate"]
        assert len(result["warnings"]) >= 2  # At least 2 warnings

    def test_empty_dataset(self):
        """Should handle empty dataset gracefully"""
        columns = ["id", "name"]
        rows = []

        result = detect_data_characteristics(columns, rows)

        # Should not crash, should return safe defaults
        assert result["sampling_appropriate"]
        assert len(result["warnings"]) == 0

    def test_non_sequential_ids(self):
        """Should not flag non-sequential IDs"""
        columns = ["uuid", "name"]
        rows = [
            {"uuid": f"abc-{i*7}", "name": f"item{i}"}  # Non-sequential
            for i in range(100)
        ]

        result = detect_data_characteristics(columns, rows)

        assert not result["has_id_sequence"]

    def test_low_variance_numeric(self):
        """Should not flag low variance as outliers"""
        columns = ["id", "price"]
        rows = [{"id": i, "price": 100 + (i % 10)} for i in range(100)]  # Low variance

        result = detect_data_characteristics(columns, rows)

        assert not result["has_outliers_risk"]


class TestSamplingDecisionLogic:
    """Test sampling decision tree"""

    @pytest.mark.skip(reason="Integration test - not yet implemented")
    def test_small_dataset_no_sampling(self):
        """Datasets <= 1000 rows should not be sampled"""
        # This would be an integration test with execute_and_analyze
        # For now, just document the expected behavior
        pass

    @pytest.mark.skip(reason="Integration test - not yet implemented")
    def test_large_normal_dataset_uses_sampling(self):
        """Large datasets (>1000) with normal characteristics should be sampled"""
        pass

    @pytest.mark.skip(reason="Integration test - not yet implemented")
    def test_medium_biased_dataset_no_sampling(self):
        """< 2500 rows with bias should analyze full dataset"""
        pass

    @pytest.mark.skip(reason="Integration test - not yet implemented")
    def test_large_biased_dataset_sampling_with_warnings(self):
        """≥ 2500 rows with bias should sample + add strong warnings"""
        pass


class TestWarningMessages:
    """Test that warning messages are helpful"""

    def test_time_series_warning_mentions_trends(self):
        """Time-series warnings should mention trends"""
        columns = ["created_at", "value"]
        rows = [{"created_at": "2024-01-01", "value": 100} for _ in range(100)]

        result = detect_data_characteristics(columns, rows)

        assert any("trend" in w.lower() or "seasonal" in w.lower() or "recent" in w.lower()
                  for w in result["warnings"])

    def test_sequential_warning_mentions_recent_records(self):
        """Sequential ID warnings should mention recent records"""
        columns = ["id", "name"]
        rows = [{"id": i, "name": f"item{i}"} for i in range(1, 101)]

        result = detect_data_characteristics(columns, rows)

        assert any("recent" in w.lower() or "added" in w.lower()
                  for w in result["warnings"])

    def test_variance_warning_mentions_outliers(self):
        """High variance warnings should mention outliers"""
        columns = ["id", "value"]
        rows = [{"id": i, "value": 10} for i in range(95)]
        rows += [{"id": i, "value": 10000} for i in range(95, 100)]

        result = detect_data_characteristics(columns, rows)

        assert any("outlier" in w.lower() or "rare" in w.lower() or "high-value" in w.lower()
                  for w in result["warnings"])
