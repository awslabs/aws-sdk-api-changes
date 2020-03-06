import logging

from botocore import hooks, model, xform_name
from botocore.docs.docstring import ClientMethodDocstring
from docutils.core import publish_parts
from docutils.writers.html5_polyglot import HTMLTranslator, Writer

log = logging.getLogger("apichanges.model")


class ServiceModel(model.ServiceModel):
    def __init__(self, service_description, service_name=None):
        super(ServiceModel, self).__init__(service_description, service_name)
        # Use our shape factory
        self._shape_resolver = ShapeResolver(service_description.get("shapes", {}))


class ShapeVisitor(object):
    # we use visitors due to the presence of recursive
    # self/circular references in shapes, for which we
    # track seen/stack.

    # all of these visitors would benefit significantly
    # from a cache on shape.

    DEFAULT_VALUE = ()

    def __init__(self):
        self.seen = set()

    def process(self, shape, *params):
        skind = type(shape)
        stype = repr(shape)
        if stype in self.seen:
            return self.DEFAULT_VALUE
        self.seen.add(stype)
        try:
            if skind is Shape:
                return self.visit_shape(shape, *params)
            elif skind is StructureShape:
                return self.visit_structure(shape, *params)
            elif skind is ListShape:
                return self.visit_list(shape, *params)
            elif skind is MapShape:
                return self.visit_map(shape, *params)
            elif skind is StringShape:
                return self.visit_string(shape, *params)
        finally:
            self.seen.remove(stype)


class EqualityVisitor(ShapeVisitor):

    DEFAULT_VALUE = True

    def visit_structure(self, shape, other):
        # type change to struct
        if type(shape) != type(other):
            return True
        added = set(shape.members).difference(other.members)
        if added:
            return False
        for m in shape.members:
            if not self.process(shape.members[m], other.members[m]):
                return False
        return True

    def visit_list(self, shape, other):
        return self.process(shape.member, other.member)

    def visit_string(self, shape, other):
        return shape.enum == other.enum

    def visit_shape(self, shape, other):
        return repr(shape) == repr(other)

    def visit_map(self, shape, other):
        return self.process(shape.key, other.key) and self.process(
            shape.value, other.value
        )


class ReferenceVisitor(ShapeVisitor):
    def visit_structure(self, shape, name):
        for m in shape.members.values():
            if self.process(m, name):
                return True
        return False

    def visit_list(self, shape, shape_name):
        return self.process(shape.member, shape_name)

    def visit_map(self, shape, shape_name):
        return self.process(shape.key, shape_name) or self.process(
            shape.value, shape_name
        )

    def visit_string(self, shape, shape_name):
        return False

    def visit_shape(self, shape, shape_name):
        return False


class TypeRepr(ShapeVisitor):
    def visit_structure(self, shape):
        d = {}
        for k, m in shape.members.items():
            d[k] = self.process(m)
        return d

    def visit_list(self, shape):
        return [self.process(shape.member)]

    def visit_map(self, shape):
        return {self.process(shape.key): self.process(shape.value)}

    def visit_string(self, shape):
        if shape.enum:
            return " | ".join(shape.enum)
        return "string"

    def visit_shape(self, shape):
        return shape.type_name


class DeltaVisitor(ShapeVisitor):
    def visit_structure(self, new, other):
        if type(new) != type(other):
            return TypeRepr().process(new)
        added = set(new.members).difference(other.members)
        modified = {a: TypeRepr().process(new.members[a]) for a in added}
        for m in new.members:
            if m in added:
                continue
            md = self.process(new.members[m], other.members[m])
            if md:
                modified[m] = md
        return modified

    def visit_list(self, new, other):
        return self.process(new.member, other.member)

    def visit_map(self, new, other):
        return self.process(new.value, other.value)

    def visit_string(self, new, other):
        return set(new.enum).difference(other.enum)

    def visit_shape(self, new, other):
        return []


class ComparableShape(object):
    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return EqualityVisitor().process(self, other)

    def references(self, shape_name):
        return ReferenceVisitor().process(self, shape_name)

    def delta(self, other):
        return DeltaVisitor().process(self, other)


class StructureShape(ComparableShape, model.StructureShape):
    pass


class ListShape(ComparableShape, model.ListShape):
    pass


class MapShape(ComparableShape, model.MapShape):
    pass


class StringShape(ComparableShape, model.StringShape):
    pass


class Shape(ComparableShape, model.Shape):
    pass


class ShapeResolver(model.ShapeResolver):

    # Any type not in this mapping will default to the Shape class.
    SHAPE_CLASSES = {
        "structure": StructureShape,
        "list": ListShape,
        "map": MapShape,
        "string": StringShape,
    }

    DEFAULT_SHAPE = Shape

    # override method to insert default shape
    def get_shape_by_name(self, shape_name, member_traits=None):
        try:
            shape_model = self._shape_map[shape_name]
        except KeyError:
            raise model.NoShapeFoundError(shape_name)
        try:
            shape_cls = self.SHAPE_CLASSES.get(shape_model["type"], self.DEFAULT_SHAPE)
        except KeyError:
            raise model.InvalidShapeError(
                "Shape is missing required key 'type': %s" % shape_model
            )
        if member_traits:
            shape_model = shape_model.copy()
            shape_model.update(member_traits)
        result = shape_cls(shape_name, shape_model, self)
        return result


def diff_model(new, old=None):
    new = ServiceModel(new)
    log.debug("delta diffing service:%s", new.service_name)
    if old:
        old = ServiceModel(old)
        new_methods = set(new.operation_names).difference(old.operation_names)
    else:
        new_methods = set(new.operation_names)

    changes = []
    for n in new_methods:
        changes.append(NewMethod(new, n))

    if not old:
        return ServiceChange(new, changes, new=True)

    old_shapes = set(old.shape_names)
    modified_shapes = []

    # TODO: with a shape cache for equality/delta we could avoid
    # extraneous compares on shape recursion.
    for s in new.shape_names:
        ns = new.shape_for(s)
        if s not in old_shapes:
            continue
        os = old.shape_for(s)
        if ns == os:  # equality visitor
            continue
        delta = ns.delta(os)
        if delta:
            modified_shapes.append((s, delta))

    mshape_map = dict(modified_shapes)
    for op in new.operation_names:
        op_delta = {}
        op_shape = new.operation_model(op)
        if op_shape.input_shape and op_shape.input_shape.name in mshape_map:
            op_delta["request"] = d_i = mshape_map[op_shape.input_shape.name]
        if op_shape.output_shape and op_shape.output_shape.name in mshape_map:
            op_delta["response"] = mshape_map[op_shape.output_shape.name]

        # sigh ec2 service specific hack
        if (
            new.service_name == "ec2"
            and "request" in op_delta
            and "TagSpecifications" in d_i
        ):
            d_i.pop("TagSpecifications")
            if not d_i:
                op_delta.pop("request")
        if not op_delta:
            continue
        if len(op_delta) == 2 and op_delta["request"] == op_delta["response"]:
            op_delta = {"both": op_delta["request"]}
        changes.append(UpdatedMethod(new.service_name, op, op_delta))

    if changes:
        return ServiceChange(new, changes)


class ReleaseDelta(object):
    # Top level container for all the changes
    # within a given commit/release.
    def __init__(self, info, service_changes):
        self.commit = info
        self.service_changes = service_changes

    def __iter__(self):
        return iter(self.service_changes)

    def __len__(self):
        return len(self.service_changes)

    def __repr__(self):
        return (
            "<release:{commit[tag]} created:{commit[created_at]:%Y-%m-%d} "
            "commit:{commit[commit_id]:.5} services:{service_count} "
            "changes:{change_count}>"
        ).format(
            commit=self.commit,
            service_count=len({s.name for s in self}),
            change_count=sum([len(s) for s in self]),
        )


class ServiceChange(object):
    def __init__(self, service, changes, new=False):
        self.new = new
        self.service = service
        self.changes = changes
        self.count_new = self.count_updated = 0
        for c in self.changes:
            if c.type == "new":
                self.count_new += 1
            else:
                self.count_updated += 1
        self.commit = {}
        self.logs = ()

    @property
    def name(self):
        return self.service.service_name.lower()

    @property
    def title(self):
        return self.service.metadata.get("serviceFullName", self.name)

    def __len__(self):
        return len(self.changes)

    def __iter__(self):
        return iter(self.changes)

    def __repr__(self):
        return (
            "<service:{name} date:{commit[created_at]:%Y-%m-%d} "
            "updated:{updated} new:{new} logs:{logs}>"
        ).format(
            name=self.name,
            commit=self.commit,
            updated=self.count_updated,
            new=self.count_new,
            logs=self.logs and "yes" or "no",
        )

    LOG_ID_MAP = {
        "Elastic Load Balancing v2": "elbv2",
        "Lex Runtime Service": "lexruntime",
        "SFN": "stepfunctions",
        "IoT 1Click Devices Service": "iot1click-devices",
        "SageMaker A2I Runtime": "augmentedairuntime",
        "Cognito Identity Provider": "cognitoidentityserviceprovider",
        # next two might be a specific hack around a particular release/feature
        "Cost Explorer": "savingsplans",
        "Budgets": "savingsplans",
    }

    def associate_logs(self, change_log):
        candidates = (
            self.LOG_ID_MAP.get(self.service.metadata.get("serviceId")),
            self.service.metadata.get("serviceId"),
            self.service.metadata.get("signingName"),
            self.service.metadata.get("endpointPrefix"),
            # sso oidc
            self.service.metadata.get("serviceAbbreviation", "").replace(" ", "-"),
            "-".join(
                [
                    c
                    for c in self.service.metadata.get("uid", "").split("-")
                    if not c.isdigit()
                ]
            ),
            self.service.metadata.get("endpointPrefix", "").replace("-", ""),
            self.service.metadata.get("serviceId", "").replace(" ", ""),
            self.service.metadata.get("serviceId", "") + "service",
            self.service.service_name.replace("-", "") + "service",
            self.service.metadata.get("serviceId", "").replace(" ", "-"),
        )

        if not change_log:
            return
        logs = ()
        for c in filter(None, candidates):
            logs = change_log.get(c.lower(), ())
            if logs:
                break
        if not logs:
            log.warning(
                "%s no change log entry found: %s", self.name, list(change_log.keys())
            )
        self.logs = logs


class Change(object):
    @property
    def service_name(self):
        return self.service.service_name

    def render_operation(self):
        # try and reuse botocore's sphinx doc infrastructure.
        method_doc = ClientMethodDocstring(
            operation_model=self.op,
            method_name=self.op.name,
            event_emitter=hooks.HierarchicalEmitter(),
            method_description=self.op.documentation,
            example_prefix="client.%s" % xform_name(self.op.name),
            include_signature=False,
        )
        return self._render_docutils(method_doc)

    def _render_docutils(self, method_doc):
        method_writer = Writer()
        method_writer.translator_class = HTMLTranslator
        parts = publish_parts(
            str(method_doc),
            settings_overrides={"report_level": 4},
            writer=method_writer,
        )
        return parts["fragment"]


class NewMethod(Change):

    type = "new"

    def __init__(self, service, op):
        self.service = service
        self.op = op

    def __repr__(self):
        return "New Method: service:{} method:{}".format(self.service_name, self.op)


class UpdatedMethod(Change):

    type = "updated"

    def __init__(self, service, op, delta):
        self.service = service
        self.op = op
        self.delta = delta

    def __repr__(self):
        return ("Updated Method: service:{} method:{} " "delta:{}").format(
            self.service, self.op, self.delta
        )
