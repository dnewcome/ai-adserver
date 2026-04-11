# Import all models here so SQLAlchemy's mapper registry is fully populated
# before any model is used in a query. Import this module anywhere models
# are used outside the FastAPI request context (e.g. Celery tasks).
from models.advertiser import Advertiser  # noqa: F401
from models.campaign import Campaign  # noqa: F401
from models.impression import Impression  # noqa: F401
from models.publisher import InventoryZone, Publisher  # noqa: F401
