from datetime import datetime
from dataclasses import dataclass
from dataclasses_json import dataclass_json
from typing import List, Dict, Any


@dataclass_json
@dataclass
class ServiceChange:
    name: str
    title: str
    change_log: str
    new: bool
    ops_added: List[str]
    ops_updated: List[str]
    ops_changes: Dict[str, Any]
    model_file: str

    @classmethod
    def from_changes(cls, service_changes):
        for s in service_changes:
            yield cls(
                name=s.name,
                title=s.title,
                new=s.new,
                model_file=s.model_file,
                change_log="\n".join(s.logs),
                ops_added=[c.op for c in s if c.type == "new"],
                ops_updated=[c.op for c in s if c.type == "updated"],
                ops_changes={c.op: c.delta for c in s if c.type == "updated"},
            )

    @property
    def count_new(self):
        return len(self.ops_added)

    @property
    def count_updated(self):
        return len(self.ops_updated)

    @property
    def slug(self):
        t = "{c.name} - "
        if self.new:
            t += "new service - {c.count_new} methods "
        else:
            if self.count_new:
                t += "{c.count_new} new "
            if self.count_updated:
                t += "{c.count_updated} updated"
        return t.format(c=self)

    def __len__(self):
        return len(self.ops_added) + len(self.ops_updated)


@dataclass_json
@dataclass
class Commit:
    id: str
    tag: str
    created: datetime
    service_changes: List[ServiceChange]

    def select(self, service_name: str) -> List[ServiceChange]:
        for s in self:
            if s.name == service_name:
                yield s

    def __iter__(self):
        return iter(self.service_changes)

    @property
    def size(self):
        return sum([len(s) for s in self.service_changes])

    @classmethod
    def from_commits(cls, releases):
        for r in releases:
            yield cls(
                id=r.commit["commit_id"],
                tag=r.commit["tag"],
                created=r.commit["created_at"],
                service_changes=list(ServiceChange.from_changes(r)),
            )
