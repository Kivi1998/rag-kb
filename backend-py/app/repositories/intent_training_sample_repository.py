"""对应 repository/IntentTrainingSampleRepository.java —— Java 版只继承 JpaRepository,
没有任何自定义查询方法,这里同样只提供 BaseRepository 的通用 CRUD(写入训练样本用 save())。"""

from app.models.intent_training_sample import IntentTrainingSample
from app.repositories.base import BaseRepository


class IntentTrainingSampleRepository(BaseRepository[IntentTrainingSample]):
    model = IntentTrainingSample
