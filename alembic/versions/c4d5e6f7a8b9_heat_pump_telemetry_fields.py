"""Heat-pump telemetry: room sensors, flow temp, weather compensation

The first version of `fetch-heatpump` collected zones (setpoints/modes), live
COP and lifetime counters. That is enough to see what the controller is doing
but not enough to answer the heating questions:

- room temperature lives on the **sensors** (Cosy Pods), not on the zone
- COP depends on **flow temperature**, which was not collected
- weather compensation (enabled + range) explains the flow temp

Adds those columns. `sensors` is a JSONB list of
`{code, temperature_c, humidity, online, read_at}`.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('heat_pump_data', sa.Column('flow_temp_c', sa.Float(), nullable=True))
    op.add_column('heat_pump_data', sa.Column('sensors', JSONB(), nullable=True))
    op.add_column('heat_pump_data', sa.Column('weather_comp_enabled', sa.Boolean(), nullable=True))
    op.add_column('heat_pump_data', sa.Column('weather_comp_min_c', sa.Float(), nullable=True))
    op.add_column('heat_pump_data', sa.Column('weather_comp_max_c', sa.Float(), nullable=True))
    op.add_column('heat_pump_data', sa.Column('controller_state', sa.String(), nullable=True))
    op.add_column('heat_pump_data', sa.Column('connected', sa.Boolean(), nullable=True))
    op.add_column('heat_pump_data', sa.Column('model', sa.String(), nullable=True))


def downgrade() -> None:
    for column in ('flow_temp_c', 'sensors', 'weather_comp_enabled',
                   'weather_comp_min_c', 'weather_comp_max_c', 'controller_state',
                   'connected', 'model'):
        op.drop_column('heat_pump_data', column)
