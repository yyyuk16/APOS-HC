from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from database import Base

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(String(50), nullable=False)
    individual_id = Column(String(50), nullable=False)
    data_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
