import httpx
import respx

from vboard import delivery
from vboard.config import VestaboardConfig

GRID = [[0] * 22 for _ in range(6)]


@respx.mock
def test_cloudrw_send_posts_grid_with_key_header():
    route = respx.post("https://rw.vestaboard.com/").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    delivery.CloudRW("rwkey").send(GRID)
    req = route.calls.last.request
    assert req.headers["X-Vestaboard-Read-Write-Key"] == "rwkey"


@respx.mock
def test_cloudrw_raises_on_error():
    respx.post("https://rw.vestaboard.com/").mock(
        return_value=httpx.Response(401, text="nope")
    )
    try:
        delivery.CloudRW("rwkey").send(GRID)
        raise AssertionError("expected DeliveryError")
    except delivery.DeliveryError:
        pass


def test_factory_selects_cloud():
    impl = delivery.make_delivery(VestaboardConfig(backend="cloud", cloud_key="k"))
    assert isinstance(impl, delivery.CloudRW)


def test_local_send_not_implemented():
    impl = delivery.make_delivery(
        VestaboardConfig(backend="local", local_endpoint="http://x", local_key="k")
    )
    try:
        impl.send(GRID)
        raise AssertionError("expected NotImplementedError")
    except NotImplementedError:
        pass
