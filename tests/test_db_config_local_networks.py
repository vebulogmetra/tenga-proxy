import ipaddress

from src.db.config import LOCAL_NETWORKS


def test_local_networks_are_valid_cidrs_and_unique():
    parsed = [ipaddress.ip_network(n) for n in LOCAL_NETWORKS]
    assert len(parsed) == len(set(parsed))
    assert "127.0.0.0/8" in LOCAL_NETWORKS
    assert "fe80::/10" in LOCAL_NETWORKS
    assert isinstance(LOCAL_NETWORKS, tuple)
