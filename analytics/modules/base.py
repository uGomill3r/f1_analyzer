# analytics/modules/base.py

from abc import ABC, abstractmethod

class BaseAnalysisModule(ABC):
    name = "base"

    @abstractmethod
    def get_queryset(self, filters):
        pass

    @abstractmethod
    def transform(self, qs, filters):
        pass

    def serialize(self, data):
        return data

    def run(self, filters):
        qs = self.get_queryset(filters)
        data = self.transform(qs, filters)
        return self.serialize(data)