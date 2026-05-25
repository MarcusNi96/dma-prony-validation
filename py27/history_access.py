"""Python 2.7-compatible History Access module for Abaqus 2022 written by Copilot.

This module preserves the public API used by scripts:
- HistoryAccess
- concatenate
- export
- plot
"""

from __future__ import print_function

import io
import json
import logging
import os
import sys
from itertools import groupby
from matplotlib import pyplot as plt


class _UserList(object):
    """Small UserList-compatible container for Python 2/3 portability."""

    def __init__(self, initlist=None):
        self.data = list(initlist) if initlist is not None else []

    def append(self, item):
        self.data.append(item)

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        return self.data[index]

logger = logging.getLogger(__name__)

PY2 = sys.version_info[0] == 2


def _builtin_type(name, default):
    builtins_obj = __builtins__
    if isinstance(builtins_obj, dict):
        return builtins_obj.get(name, default)
    return getattr(builtins_obj, name, default)


string_types = (str, _builtin_type("unicode", str))
integer_types = (int, _builtin_type("long", int))


def __dir__():
    return ["HistoryAccess", "concatenate", "export", "plot"]


class Metadata(object):
    """Metadata and location info for a single history output (internal use)."""

    def __init__(
        self,
        name,
        region_description,
        output_description,
        step,
        assembly,
        instance,
        region,
        element,
        node,
        integration_point,
        section_point,
    ):
        self.name = name
        self.region_description = region_description
        self.output_description = output_description
        self.step = step
        self.assembly = assembly
        self.instance = instance
        self.region = region
        self.element = element
        self.node = node
        self.integration_point = integration_point
        self.section_point = section_point

    @property
    def description(self):
        return "{0}, {1}".format(self.region_description, self.output_description)


class FilterFlags(object):
    """Filter flags specific to one history output (internal use)."""

    _fields = [
        "name",
        "description",
        "step",
        "assembly",
        "instance",
        "region",
        "element",
        "node",
        "integration_point",
        "section_point",
    ]

    def __init__(self):
        for key in self._fields:
            setattr(self, key, False)

    @property
    def is_filtered(self):
        return any(getattr(self, key) for key in self._fields)

    def reset(self, key):
        setattr(self, key, False)

    def reset_all(self):
        for key in self._fields:
            self.reset(key)


class HistoryData(object):
    """Container for history output and related data (internal use)."""

    def __init__(self, abq_output, metadata, filter_flags):
        self.abq_output = abq_output
        self.metadata = metadata
        self.filter_flags = filter_flags


class HistoryDatabase(_UserList):
    """Database to access HistoryData objects (internal use)."""

    def __init__(self, odb):
        _UserList.__init__(self)

        for step in odb.steps.values():
            for h_region in step.historyRegions.values():
                for h_output in h_region.historyOutputs.values():
                    point = h_region.point
                    assembly_name = point.assembly.name if point.assembly else None
                    instance_name = point.instance.name if point.instance else None
                    region_name = point.region.name if point.region else None
                    element_label = point.element.label if point.element else None
                    node_label = point.node.label if point.node else None
                    ip = point.ipNumber if point.ipNumber else None
                    sp = point.sectionPoint.number if point.sectionPoint else None

                    metadata = Metadata(
                        name=h_output.name,
                        region_description=h_region.description,
                        output_description=h_output.description,
                        step=step.name,
                        assembly=assembly_name,
                        instance=instance_name,
                        region=region_name,
                        element=element_label,
                        node=node_label,
                        integration_point=ip,
                        section_point=sp,
                    )

                    self.data.append(
                        HistoryData(
                            abq_output=h_output,
                            metadata=metadata,
                            filter_flags=FilterFlags(),
                        )
                    )

    @property
    def number_of_items(self):
        return len(self.data)

    @property
    def number_of_selected_items(self):
        return len(self.selected_items)

    @property
    def selected_items(self):
        return [h_data for h_data in self.data if not h_data.filter_flags.is_filtered]

    def reset_all_filters(self):
        for h_data in self.data:
            h_data.filter_flags.reset_all()

    def reset_filter_for_field(self, key):
        for h_data in self.data:
            h_data.filter_flags.reset(key)

    def apply_filter(self, key, input_data, exclude):
        for h_data in self.selected_items:
            field_value = getattr(h_data.metadata, key)
            apply_filter = False

            if exclude:
                if field_value in input_data:
                    apply_filter = True
            else:
                if field_value not in input_data:
                    apply_filter = True

            if apply_filter:
                setattr(h_data.filter_flags, key, True)

    def apply_filter_with_partial_match(self, key, input_data, exclude):
        input_data_str = []
        for data in input_data:
            if not isinstance(data, string_types):
                data = str(data)
                msg = (
                    "Unsupported type {0} for value {1} in {2}. Filtering with "
                    "partial matching requires strings."
                ).format(type(data), data, input_data)
                logger.debug(msg)
            input_data_str.append(data)

        input_data_lower = [s.lower() for s in input_data_str]

        for h_data in self.selected_items:
            field_value = getattr(h_data.metadata, key)
            apply_filter = False

            if not isinstance(field_value, string_types):
                field_value = str(field_value)
                msg = (
                    "Unsupported type {0} for value {1} in {2}. Filtering with "
                    "partial match requires strings."
                ).format(type(field_value), field_value, h_data)
                logger.debug(msg)

            field_value_lower = field_value.lower()

            if exclude:
                for partial in input_data_lower:
                    if partial in field_value_lower:
                        apply_filter = True
            else:
                match_found = False
                for partial in input_data_lower:
                    if partial in field_value_lower:
                        match_found = True
                        break
                if not match_found:
                    apply_filter = True

            if apply_filter:
                setattr(h_data.filter_flags, key, True)


class HistoryOutput(object):
    """Combines history output data and metadata for analysis and plotting."""

    _export_fields = [
        "name",
        "region_description",
        "output_description",
        "step",
        "assembly",
        "instance",
        "region",
        "element",
        "node",
        "integration_point",
        "section_point",
        "time_offset",
        "data",
        "conjugate_data",
    ]

    def __init__(
        self,
        name,
        region_description,
        output_description,
        step,
        assembly,
        instance,
        region,
        element,
        node,
        integration_point,
        section_point,
        time_offset,
        data,
        conjugate_data,
    ):
        self.name = name
        self.region_description = region_description
        self.output_description = output_description
        self.step = step
        self.assembly = assembly
        self.instance = instance
        self.region = region
        self.element = element
        self.node = node
        self.integration_point = integration_point
        self.section_point = section_point
        self.time_offset = time_offset
        self.data = data
        self.conjugate_data = conjugate_data

    @property
    def description(self):
        return "{0}, {1}".format(self.region_description, self.output_description)

    @property
    def concatenate_id(self):
        return (
            self.name,
            self.description,
            self.assembly,
            self.instance,
            self.region,
            self.element,
            self.node,
            self.integration_point,
            self.section_point,
        )

    def list_repr(self):
        return (
            "<HistoryOutput: step='{0}', name='{1}', description='{2}', data=...>"
        ).format(self.step, self.name, self.description)

    def to_dict(self):
        return dict((key, getattr(self, key)) for key in self._export_fields)


class HistoryResults(_UserList):
    """Container for HistoryOutput with a concise list representation."""

    def __init__(self):
        _UserList.__init__(self)

    def __repr__(self):
        if self.data:
            lines = [d.list_repr() for d in self.data]
            return "[{0}]".format(",\n ".join(lines))
        return "[]"


class HistoryAccess(object):
    """Fluent interface to access/filter history output."""

    def __init__(self, odb):
        self._odb = odb
        self._filters = []
        self._database = HistoryDatabase(odb)
        self._time_offsets = self._compute_time_offsets()

    @staticmethod
    def _convert_input_to_list(base_type, user_input):
        if base_type is str:
            expected_type = string_types
            expected_name = "str"
        elif base_type is int:
            expected_type = integer_types
            expected_name = "int"
        else:
            expected_type = (base_type,)
            expected_name = getattr(base_type, "__name__", str(base_type))

        if isinstance(user_input, expected_type):
            input_data = [user_input]
        elif isinstance(user_input, (list, tuple)):
            input_data = list(user_input)
        else:
            raise ValueError(
                "Unsupported type '{0}' for value {1}, expected '{2}'.".format(
                    type(user_input).__name__, user_input, expected_name
                )
            )

        for item in input_data:
            if not isinstance(item, expected_type):
                raise ValueError(
                    "Unsupported type '{0}' for value {1}, expected '{2}'.".format(
                        type(item).__name__, item, expected_name
                    )
                )

        return input_data

    def _save_filter_info(self, key, input_data, reset, exclude, partial):
        flags = []
        if reset:
            flags.append("reset=True")
        if exclude:
            flags.append("exclude=True")
        if partial:
            flags.append("partial_match=True")
        self._filters.append({"key": key, "input": input_data, "flags": flags})

    def _generic_fluent_interface(
        self, key, base_type, user_input, exclude=False, reset=False, partial=False
    ):
        input_data = self._convert_input_to_list(base_type=base_type, user_input=user_input)

        if reset:
            self._database.reset_filter_for_field(key=key)

        if partial:
            self._database.apply_filter_with_partial_match(
                key=key, input_data=input_data, exclude=exclude
            )
        else:
            self._database.apply_filter(key=key, input_data=input_data, exclude=exclude)

        self._save_filter_info(
            key=key,
            input_data=user_input,
            reset=reset,
            exclude=exclude,
            partial=partial,
        )
        return self

    def _compute_time_offsets(self):
        offsets = {}
        time = 0.0
        for step in self._odb.steps.values():
            offsets[step.name] = time
            time += step.timePeriod
        return offsets

    def __repr__(self):
        return "<HistoryAccess: {0} out of {1} selected>".format(
            self._database.number_of_selected_items, self._database.number_of_items
        )

    def __len__(self):
        return self._database.number_of_selected_items

    def status(self):
        txt = "\n ODB Path: {0}\n".format(self._odb.path)

        if self._filters:
            lines = ["", " Filters:", ""]
            for i, f_item in enumerate(self._filters, start=1):
                lines.append("  {0}. TYPE  : {1}".format(i, f_item["key"]))
                lines.append("     INPUT : {0}".format(f_item["input"]))
                flags_txt = ", ".join(f_item["flags"]) if f_item["flags"] else "None"
                lines.append("     FLAGS : {0}".format(flags_txt))
                lines.append("")
        else:
            lines = ["\n Filters:  None\n"]

        txt += "\n".join(lines)

        if self._database.selected_items:
            step_names = [h_data.metadata.step for h_data in self._database.selected_items]
            max_step_len = max(max((len(name) for name in step_names)), len("Step"))

            names = [h_data.metadata.name for h_data in self._database.selected_items]
            max_name_len = max(max((len(name) for name in names)), len("Name"))

            lines = []
            for n, h_data in enumerate(self._database.selected_items, start=1):
                lines.append(
                    " {0:3d} | {1:<{sw}} | {2:<{nw}} | {3}".format(
                        n,
                        h_data.metadata.step,
                        h_data.metadata.name,
                        h_data.metadata.description,
                        sw=max_step_len,
                        nw=max_name_len,
                    )
                )
            selected = "\n".join(lines)

            txt += (
                "\n Selected {0} out of {1} history outputs:\n"
                "\n   # | {2:^{sw}} | {3:^{nw}} | Description: region, output\n"
                "  --- {4} {5} -----------------------------\n"
                "{6}"
            ).format(
                self._database.number_of_selected_items,
                self._database.number_of_items,
                "Step",
                "Name",
                "-" * (max_step_len + 2),
                "-" * (max_name_len + 2),
                selected,
                sw=max_step_len,
                nw=max_name_len,
            )
        else:
            txt += "\n Selected {0} out of {1} history outputs.\n".format(
                self._database.number_of_selected_items,
                self._database.number_of_items,
            )

        print(txt)

    def reset(self):
        self._filters = []
        self._database.reset_all_filters()

    def fetch(self, reset=True):
        results = HistoryResults()
        for item in self._database.selected_items:
            output = HistoryOutput(
                name=item.metadata.name,
                region_description=item.metadata.region_description,
                output_description=item.metadata.output_description,
                step=item.metadata.step,
                assembly=item.metadata.assembly,
                instance=item.metadata.instance,
                region=item.metadata.region,
                element=item.metadata.element,
                node=item.metadata.node,
                integration_point=item.metadata.integration_point,
                section_point=item.metadata.section_point,
                time_offset=self._time_offsets[item.metadata.step],
                data=item.abq_output.data,
                conjugate_data=item.abq_output.conjugateData,
            )
            results.append(output)

        if reset:
            self.reset()

        return results

    def name(self, user_input, exclude=False, reset=False, partial=True):
        return self._generic_fluent_interface(
            key="name",
            base_type=str,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=partial,
        )

    def description(self, user_input, exclude=False, reset=False, partial=True):
        return self._generic_fluent_interface(
            key="description",
            base_type=str,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=partial,
        )

    def step(self, user_input, exclude=False, reset=False, partial=True):
        return self._generic_fluent_interface(
            key="step",
            base_type=str,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=partial,
        )

    def assembly(self, user_input, exclude=False, reset=False, partial=True):
        return self._generic_fluent_interface(
            key="assembly",
            base_type=str,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=partial,
        )

    def instance(self, user_input, exclude=False, reset=False, partial=True):
        return self._generic_fluent_interface(
            key="instance",
            base_type=str,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=partial,
        )

    def region(self, user_input, exclude=False, reset=False, partial=True):
        return self._generic_fluent_interface(
            key="region",
            base_type=str,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=partial,
        )

    def element(self, user_input, exclude=False, reset=False):
        return self._generic_fluent_interface(
            key="element",
            base_type=int,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=False,
        )

    def node(self, user_input, exclude=False, reset=False):
        return self._generic_fluent_interface(
            key="node",
            base_type=int,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=False,
        )

    def integration_point(self, user_input, exclude=False, reset=False):
        return self._generic_fluent_interface(
            key="integration_point",
            base_type=int,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=False,
        )

    def section_point(self, user_input, exclude=False, reset=False):
        return self._generic_fluent_interface(
            key="section_point",
            base_type=int,
            user_input=user_input,
            exclude=exclude,
            reset=reset,
            partial=False,
        )


def plot(results):
    """Generate XY plots of the provided results using matplotlib."""

    step_flag = len(set([r.step for r in results])) > 1
    assembly_flag = len(set([r.assembly for r in results])) > 1
    instance_flag = len(set([r.instance for r in results])) > 1
    region_flag = len(set([r.region for r in results])) > 1
    element_flag = len(set([r.element for r in results])) > 1
    node_flag = len(set([r.node for r in results])) > 1
    ip_flag = len(set([r.integration_point for r in results])) > 1
    sp_flag = len(set([r.section_point for r in results])) > 1

    labels = []
    for result in results:
        label = [result.name]
        if step_flag:
            value = str(result.step) if result.step else "-"
            label.append("Step={0}".format(value))
        if assembly_flag:
            value = str(result.assembly) if result.assembly else "-"
            label.append("Assembly={0}".format(value))
        if instance_flag:
            value = str(result.instance) if result.instance else "-"
            label.append("Instance={0}".format(value))
        if region_flag:
            value = str(result.region) if result.region else "-"
            label.append("Region={0}".format(value))
        if element_flag:
            value = str(result.element) if result.element else "-"
            label.append("Element={0}".format(value))
        if node_flag:
            value = str(result.node) if result.node else "-"
            label.append("Node={0}".format(value))
        if ip_flag:
            value = str(result.integration_point) if result.integration_point else "-"
            label.append("IP={0}".format(value))
        if sp_flag:
            value = str(result.section_point) if result.section_point else "-"
            label.append("SP={0}".format(value))

        labels.append(", ".join(label))

    for result, label in zip(results, labels):
        x, y = zip(*result.data)
        plt.plot(x, y, label=label)

    plt.legend(loc="best")
    plt.rc("grid", linestyle="--")
    plt.grid(True)
    plt.show()


def export(results, file_name):
    """Export the history results as JSON files."""

    root, _ = os.path.splitext(file_name)
    file_path = root + ".json"
    with io.open(file_path, mode="w", encoding="utf-8") as handle:
        data = [result.to_dict() for result in results]
        json_text = json.dumps(data, indent=4, ensure_ascii=False)
        if PY2 and isinstance(json_text, str):
            json_text = json_text.decode("utf-8")
        handle.write(json_text)


def concatenate(results):
    """Combine data from different steps to form a continuous curve."""

    concatenated = HistoryResults()
    sorted_results = sorted(results, key=lambda r: r.concatenate_id)

    for _, group in groupby(sorted_results, key=lambda r: r.concatenate_id):
        group = list(group)
        group_data = []
        group_steps = []

        for result in group:
            adjusted_data = [(x + result.time_offset, y) for x, y in result.data]
            group_data.extend(adjusted_data)
            group_steps.append(result.step)

        step_name = "<{0}>".format(", ".join(group_steps))

        output = HistoryOutput(
            name=group[0].name,
            region_description=group[0].region_description,
            output_description=group[0].output_description,
            step=step_name,
            assembly=group[0].assembly,
            instance=group[0].instance,
            region=group[0].region,
            element=group[0].element,
            node=group[0].node,
            integration_point=group[0].integration_point,
            section_point=group[0].section_point,
            time_offset=0.0,
            data=tuple(sorted(set(group_data))),
            conjugate_data=None,
        )
        concatenated.append(output)

    return concatenated


if __name__ == "__main__":
    print(
        "\n"
        " --------------------------------------------------------------------------\n"
        " | This module is designed to be imported, not executed. Please import it |\n"
        " | in your script or interactive session to use its functionalities.      |\n"
        " --------------------------------------------------------------------------\n"
    )
