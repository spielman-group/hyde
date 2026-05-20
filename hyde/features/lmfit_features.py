from __future__ import annotations

import copy

from hyde.features.base import FeatureCodec
from hyde.features.matplotlib_features import sorted_eligible_names
from hyde.user_interface.window_naming import resolve_requested_name


def _set_path(target, path, value):
    cursor = target
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value


def _existing_namespace_names(namespace_view):
    return sorted(str(name) for name in dict(namespace_view or {}))


def _unique_preserving_order(values):
    seen = set()
    ordered = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _normalize_optional_text(value):
    text = str(value or "").strip()
    return None if not text else text


def _parse_optional_float(text, field_name):
    stripped = str(text or "").strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid number.") from exc


def _fit_result_default_name(y_name, existing_names):
    base_name = f"{str(y_name)}_fit_result"
    existing = {str(name) for name in existing_names}
    if base_name not in existing:
        return base_name
    suffix = 0
    candidate = f"{base_name}{suffix}"
    while candidate in existing:
        suffix += 1
        candidate = f"{base_name}{suffix}"
    return candidate


def attached_display_trace(result_name, x_name, trace_id, component, label, style):
    normalized_result_name = _normalize_optional_text(result_name)
    if normalized_result_name is None:
        raise ValueError("Curve Fit attached displays require a fit result name.")
    return {
        "id": str(trace_id),
        "kind": "line",
        "x_source": (
            None
            if x_name in (None, "")
            else {"kind": "name", "value": str(x_name)}
        ),
        "y_source": {
            "kind": "attribute_path",
            "root": {"kind": "name", "value": normalized_result_name},
            "path": [str(component)],
        },
        "kwargs": {"label": str(label), **dict(style or {})},
    }


def _attached_display_trace_prefix(result_name, component):
    normalized_result_name = _normalize_optional_text(result_name)
    if normalized_result_name is None:
        raise ValueError("Curve Fit attached displays require a fit result name.")
    component_prefix = {
        "best_fit": "fit",
        "residual": "res",
    }.get(str(component))
    if component_prefix is None:
        raise ValueError(f"Unsupported attached display component: {component!r}.")
    return f"{component_prefix}_{normalized_result_name}"


def resolve_attached_display_trace_id(
    result_name,
    component,
    existing_trace_ids,
    *,
    requested_trace_id=None,
):
    prefix = _attached_display_trace_prefix(result_name, component)
    requested_name = None
    requested_trace_id = _normalize_optional_text(requested_trace_id)
    if requested_trace_id and (
        requested_trace_id == prefix or requested_trace_id.startswith(f"{prefix}_")
    ):
        requested_name = requested_trace_id
    return resolve_requested_name(
        prefix,
        existing_trace_ids,
        requested_name=requested_name,
        omit_zero=True,
    )


def restore_target_command(
    target_name,
    *,
    restore_store_name="_hyde_lmfit_live_restore",
    missing_sentinel_name="_hyde_lmfit_missing",
):
    normalized_target_name = _normalize_optional_text(target_name)
    if normalized_target_name is None:
        return ""
    return "\n".join(
        [
            f"{missing_sentinel_name} = globals().get({missing_sentinel_name!r}, object())",
            f"globals()[{missing_sentinel_name!r}] = {missing_sentinel_name}",
            f"{restore_store_name} = globals().setdefault({restore_store_name!r}, {{}})",
            (
                "_hyde_lmfit_restore_target_state = "
                f"{restore_store_name}.pop({normalized_target_name!r}, "
                f"{missing_sentinel_name})"
            ),
            (
                f"if _hyde_lmfit_restore_target_state is "
                f"{missing_sentinel_name}:"
            ),
            f"    globals().pop({normalized_target_name!r}, None)",
            "else:",
            (
                f"    globals()[{normalized_target_name!r}] = "
                "_hyde_lmfit_restore_target_state"
            ),
        ]
    )


class LmfitCodec(FeatureCodec):
    feature_name = "lmfit"
    state_version = 1

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "state_version": cls.state_version,
            "settings": {
                "fit_function_name": None,
                "y_name": None,
                "x_names": {},
                "from_target": False,
                "coefficients": {},
                "weighting_name": None,
                "suppress_screen_updates": True,
                "fit_result_name": None,
                "fit_result_name_locked": False,
                "preview_mode": "Commands",
            },
            "ui": {},
        }

    @classmethod
    def normalize_state(cls, state):
        normalized = copy.deepcopy(cls.default_state())
        if state:
            normalized["feature"] = state.get("feature", normalized["feature"])
            normalized["state_version"] = state.get(
                "state_version",
                normalized["state_version"],
            )
            settings = state.get("settings", {})
            if isinstance(settings, dict):
                normalized["settings"].update(settings)
            ui = state.get("ui", {})
            normalized["ui"] = dict(ui) if isinstance(ui, dict) else {}

        settings = normalized["settings"]
        fit_function_name = settings.get("fit_function_name")
        settings["fit_function_name"] = (
            None if fit_function_name in (None, "") else str(fit_function_name)
        )
        y_name = settings.get("y_name")
        settings["y_name"] = None if y_name in (None, "") else str(y_name)
        x_names = settings.get("x_names", {})
        if isinstance(x_names, dict):
            settings["x_names"] = {
                str(name): None if value in (None, "") else str(value)
                for name, value in x_names.items()
                if str(name)
            }
        else:
            settings["x_names"] = {}
        settings["from_target"] = bool(settings.get("from_target"))
        coefficients = settings.get("coefficients", {})
        if isinstance(coefficients, dict):
            normalized["settings"]["coefficients"] = {
                str(name): {
                    "initial_value": _normalize_optional_text(
                        dict(values or {}).get("initial_value")
                    ),
                    "vary": bool(dict(values or {}).get("vary", True)),
                    "lower_bound": _normalize_optional_text(
                        dict(values or {}).get("lower_bound")
                    ),
                    "upper_bound": _normalize_optional_text(
                        dict(values or {}).get("upper_bound")
                    ),
                    "expr": _normalize_optional_text(dict(values or {}).get("expr")),
                }
                for name, values in coefficients.items()
                if str(name)
            }
        else:
            normalized["settings"]["coefficients"] = {}
        weighting_name = settings.get("weighting_name")
        settings["weighting_name"] = (
            None if weighting_name in (None, "") else str(weighting_name).strip()
        )
        settings["suppress_screen_updates"] = bool(
            settings.get("suppress_screen_updates")
        )
        fit_result_name = settings.get("fit_result_name")
        settings["fit_result_name"] = (
            None if fit_result_name in (None, "") else str(fit_result_name).strip()
        )
        settings["fit_result_name_locked"] = bool(
            settings.get("fit_result_name_locked")
        )
        preview_mode = str(settings.get("preview_mode", "Commands") or "Commands")
        settings["preview_mode"] = (
            "Equation" if preview_mode == "Equation" else "Commands"
        )
        return normalized

    @classmethod
    def validate_state(cls, state):
        normalized = cls.normalize_state(state)
        if normalized["feature"] != cls.feature_name:
            raise ValueError(f"Expected feature={cls.feature_name!r}.")
        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.normalize_state(state)
        action_type = action.get("type")
        if action_type == "set":
            _set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            _set_path(normalized, action["path"], None)
        else:
            raise ValueError(f"Unsupported lmfit action: {action_type!r}.")
        return cls.normalize_state(normalized)

    @classmethod
    def _selected_fit_function(cls, normalized, context):
        entries = list(context.get("fit_functions", []) or [])
        entry_by_name = {str(entry.get("name")): dict(entry) for entry in entries}
        selected_name = normalized["settings"]["fit_function_name"]
        if selected_name and selected_name in entry_by_name:
            return entry_by_name[selected_name]
        return None if not entries else dict(entries[0])

    @classmethod
    def _y_options(cls, eligible_names, trace_records, from_target):
        if not from_target:
            return list(eligible_names)
        trace_y_names = _unique_preserving_order(
            record.get("y_name") for record in trace_records
        )
        narrowed = [name for name in trace_y_names if name in eligible_names]
        return narrowed

    @classmethod
    def _resolve_y_name(cls, normalized, y_options):
        selected_name = normalized["settings"]["y_name"]
        if selected_name in y_options:
            return selected_name
        return None if not y_options else y_options[0]

    @classmethod
    def _trace_defaults_for_y(cls, trace_records, y_name):
        if not y_name:
            return []
        return [
            dict(record)
            for record in trace_records
            if str(record.get("y_name") or "") == str(y_name)
        ]

    @classmethod
    def _resolve_x_rows(cls, normalized, entry, context, y_name, eligible_names):
        trace_records = cls._trace_defaults_for_y(
            context.get("trace_records", ()),
            y_name,
        )
        from_target = bool(normalized["settings"]["from_target"])
        used_names = {str(y_name)} if y_name else set()
        resolved_rows = []
        stored_x_names = dict(normalized["settings"].get("x_names", {}))

        for index, independent_var in enumerate(entry.get("independent_vars", [])):
            current_name = stored_x_names.get(independent_var)
            options = list(eligible_names)
            if current_name in options and current_name not in used_names:
                value = current_name
            else:
                preferred = None
                if from_target and trace_records and index == 0:
                    preferred = trace_records[0].get("x_name")
                if preferred in options and preferred not in used_names:
                    value = preferred
                else:
                    remaining = [
                        name for name in options if name not in used_names
                    ]
                    value = None if not remaining else remaining[0]
                    if value is None and options:
                        value = options[0]
            if value:
                used_names.add(value)
            resolved_rows.append(
                {
                    "name": str(independent_var),
                    "options": options,
                    "value": value,
                }
            )
        return resolved_rows

    @classmethod
    def _resolved_fit_result_name(cls, normalized, context, y_name):
        settings = normalized["settings"]
        explicit_name = settings.get("fit_result_name")
        if settings.get("fit_result_name_locked") and explicit_name:
            return explicit_name
        if not y_name:
            return explicit_name or ""
        return _fit_result_default_name(
            y_name,
            _existing_namespace_names(context.get("namespace_view")),
        )

    @classmethod
    def _coefficient_rows(cls, normalized, entry):
        stored_rows = dict(normalized["settings"].get("coefficients", {}))
        rows = []
        for parameter_name in entry.get("parameters", []):
            stored = dict(stored_rows.get(parameter_name, {}))
            expr = _normalize_optional_text(stored.get("expr"))
            rows.append(
                {
                    "name": str(parameter_name),
                    "initial_value": _normalize_optional_text(
                        stored.get("initial_value")
                    )
                    or "",
                    "vary": bool(stored.get("vary", True)),
                    "lower_bound": _normalize_optional_text(
                        stored.get("lower_bound")
                    )
                    or "",
                    "upper_bound": _normalize_optional_text(
                        stored.get("upper_bound")
                    )
                    or "",
                    "expr": expr or "",
                    "expression_owned": bool(expr),
                }
            )
        return rows

    @classmethod
    def _validate_configuration(
        cls,
        entry,
        y_name,
        x_rows,
        fit_result_name,
        coefficient_rows,
    ):
        if entry is None:
            return {"valid": False, "message": ""}
        if not y_name:
            return {"valid": False, "message": "Select Y data."}
        for row in x_rows:
            if row.get("value"):
                continue
            return {
                "valid": False,
                "message": f"Select X data for {row['name']}.",
            }
        if not str(fit_result_name or "").strip():
            return {"valid": False, "message": "Select a fit-result target."}
        for row in coefficient_rows:
            parameter_name = row["name"]
            if row.get("expression_owned"):
                continue
            initial_value = row.get("initial_value", "")
            if not str(initial_value or "").strip():
                return {
                    "valid": False,
                    "message": f"Parameter {parameter_name} requires an initial value.",
                }
            try:
                initial_number = _parse_optional_float(
                    initial_value,
                    f"Parameter {parameter_name} initial value",
                )
                lower_bound = _parse_optional_float(
                    row.get("lower_bound"),
                    f"Parameter {parameter_name} lower bound",
                )
                upper_bound = _parse_optional_float(
                    row.get("upper_bound"),
                    f"Parameter {parameter_name} upper bound",
                )
            except ValueError as exc:
                return {"valid": False, "message": str(exc)}
            if lower_bound is not None and upper_bound is not None and lower_bound > upper_bound:
                return {
                    "valid": False,
                    "message": (
                        f"Parameter {parameter_name} lower bound must be "
                        "less than or equal to the upper bound."
                    ),
                }
            if lower_bound is not None and initial_number < lower_bound:
                return {
                    "valid": False,
                    "message": (
                        f"Parameter {parameter_name} initial value must be "
                        "greater than or equal to the lower bound."
                    ),
                }
            if upper_bound is not None and initial_number > upper_bound:
                return {
                    "valid": False,
                    "message": (
                        f"Parameter {parameter_name} initial value must be "
                        "less than or equal to the upper bound."
                    ),
                }
        return {"valid": True, "message": ""}

    @classmethod
    def _resolved_weighting_name(cls, normalized, eligible_names):
        weighting_name = normalized["settings"].get("weighting_name")
        return weighting_name if weighting_name in eligible_names else ""

    @classmethod
    def _parameter_add_lines(cls, coefficient_rows):
        lines = []
        for row in coefficient_rows:
            parameter_name = row["name"]
            if row.get("expression_owned"):
                lines.append(
                    "_hyde_lmfit_params.add("
                    f"{parameter_name!r}, expr={row['expr']!r})"
                )
                continue
            try:
                initial_value = _parse_optional_float(
                    row.get("initial_value"),
                    f"Parameter {parameter_name} initial value",
                )
                lower_bound = _parse_optional_float(
                    row.get("lower_bound"),
                    f"Parameter {parameter_name} lower bound",
                )
                upper_bound = _parse_optional_float(
                    row.get("upper_bound"),
                    f"Parameter {parameter_name} upper bound",
                )
            except ValueError:
                return []
            if initial_value is None:
                return []
            arguments = [
                f"{parameter_name!r}",
                f"value={initial_value!r}",
                f"vary={bool(row.get('vary', True))!r}",
            ]
            if lower_bound is not None:
                arguments.append(f"min={lower_bound!r}")
            if upper_bound is not None:
                arguments.append(f"max={upper_bound!r}")
            lines.append(f"_hyde_lmfit_params.add({', '.join(arguments)})")
        return lines

    @classmethod
    def _command_preview(
        cls,
        entry,
        y_name,
        x_rows,
        fit_result_name,
        coefficient_rows,
        weighting_name,
    ):
        if entry is None:
            return ""
        lines = [
            f"_hyde_lmfit_model = lmfit.Model({entry['name']}, "
            f"independent_vars={list(entry.get('independent_vars', []))!r})"
        ]
        parameter_lines = cls._parameter_add_lines(coefficient_rows)
        if parameter_lines:
            lines.append("_hyde_lmfit_params = lmfit.Parameters()")
            lines.extend(parameter_lines)
        if (
            y_name
            and fit_result_name
            and all(row.get("value") for row in x_rows)
        ):
            fit_arguments = []
            if parameter_lines:
                fit_arguments.append("params=_hyde_lmfit_params")
            fit_arguments.extend(
                f"{row['name']}={row['value']}" for row in x_rows
            )
            if weighting_name:
                fit_arguments.append(f"weights={weighting_name}")
            lines.append(
                f"{fit_result_name} = _hyde_lmfit_model.fit("
                f"{y_name}, {', '.join(fit_arguments)})"
            )
        return "\n".join(lines)

    @classmethod
    def _equation_preview(cls, entry):
        if entry is None:
            return ""
        arguments = list(entry.get("independent_vars", [])) + list(
            entry.get("parameters", [])
        )
        return f"{entry['name']}({', '.join(arguments)})"

    @classmethod
    def _live_command_preview(
        cls,
        command_preview,
        fit_result_name,
        *,
        previous_target_name=None,
        restore_store_name="_hyde_lmfit_live_restore",
        missing_sentinel_name="_hyde_lmfit_missing",
    ):
        if not command_preview or not fit_result_name:
            return command_preview
        lines = [
            f"{missing_sentinel_name} = globals().get({missing_sentinel_name!r}, object())",
            f"globals()[{missing_sentinel_name!r}] = {missing_sentinel_name}",
            f"{restore_store_name} = globals().setdefault({restore_store_name!r}, {{}})",
        ]
        if previous_target_name and previous_target_name != fit_result_name:
            lines.extend(
                [
                    (
                        "_hyde_lmfit_previous_target_state = "
                        f"{restore_store_name}.pop({previous_target_name!r}, "
                        f"{missing_sentinel_name})"
                    ),
                    (
                        f"if _hyde_lmfit_previous_target_state is "
                        f"{missing_sentinel_name}:"
                    ),
                    f"    globals().pop({previous_target_name!r}, None)",
                    "else:",
                    (
                        f"    globals()[{previous_target_name!r}] = "
                        "_hyde_lmfit_previous_target_state"
                    ),
                ]
            )
        lines.extend(
            [
                f"if {fit_result_name!r} not in {restore_store_name}:",
                (
                    f"    {restore_store_name}[{fit_result_name!r}] = globals().get("
                    f"{fit_result_name!r}, {missing_sentinel_name})"
                ),
                command_preview,
            ]
        )
        return "\n".join(lines)

    @classmethod
    def present_state(cls, state, context=None):
        normalized = cls.validate_state(state)
        context = dict(context or {})
        entry = cls._selected_fit_function(normalized, context)
        eligible_names = sorted_eligible_names(context.get("namespace_view"))
        from_target = bool(
            normalized["settings"]["from_target"] and context.get("attached", False)
        )
        trace_records = list(context.get("trace_records", ()))
        y_options = cls._y_options(eligible_names, trace_records, from_target)
        y_name = cls._resolve_y_name(normalized, y_options)
        x_rows = (
            []
            if entry is None
            else cls._resolve_x_rows(
                normalized,
                entry,
                context,
                y_name,
                eligible_names,
            )
        )
        coefficient_rows = [] if entry is None else cls._coefficient_rows(normalized, entry)
        weighting_name = cls._resolved_weighting_name(normalized, eligible_names)
        fit_result_name = cls._resolved_fit_result_name(normalized, context, y_name)
        existing_names = _existing_namespace_names(context.get("namespace_view"))
        fit_result_options = _unique_preserving_order(existing_names + [fit_result_name])
        validation = cls._validate_configuration(
            entry,
            y_name,
            x_rows,
            fit_result_name,
            coefficient_rows,
        )
        return {
            "fit_function_entry": entry,
            "from_target": from_target,
            "fit_function_name": None if entry is None else entry["name"],
            "preview_mode": normalized["settings"]["preview_mode"],
            "y_options": y_options,
            "y_name": y_name,
            "x_rows": x_rows,
            "coefficient_rows": coefficient_rows,
            "weighting_options": [""] + list(eligible_names),
            "weighting_name": weighting_name,
            "suppress_screen_updates": bool(
                normalized["settings"].get("suppress_screen_updates")
            ),
            "execution_mode": (
                "suppressed"
                if normalized["settings"].get("suppress_screen_updates")
                else "live"
            ),
            "fit_result_name": fit_result_name,
            "fit_result_options": fit_result_options,
            "commands_preview": cls._command_preview(
                entry,
                y_name,
                x_rows,
                fit_result_name,
                coefficient_rows,
                weighting_name,
            ),
            "equation_preview": cls._equation_preview(entry),
            "valid": bool(validation["valid"]),
            "status_message": validation["message"],
        }

    @classmethod
    def state_to_python(cls, state, context=None):
        return cls.present_state(state, context=context)["commands_preview"]

    @classmethod
    def state_to_equation(cls, state, context=None):
        return cls.present_state(state, context=context)["equation_preview"]

    @classmethod
    def state_to_live_python(
        cls,
        state,
        context=None,
        *,
        previous_target_name=None,
        restore_store_name="_hyde_lmfit_live_restore",
        missing_sentinel_name="_hyde_lmfit_missing",
    ):
        presented = cls.present_state(state, context=context)
        return cls._live_command_preview(
            presented["commands_preview"],
            presented["fit_result_name"],
            previous_target_name=previous_target_name,
            restore_store_name=restore_store_name,
            missing_sentinel_name=missing_sentinel_name,
        )

    @classmethod
    def state_to_restore_target_python(
        cls,
        target_name,
        *,
        restore_store_name="_hyde_lmfit_live_restore",
        missing_sentinel_name="_hyde_lmfit_missing",
    ):
        return restore_target_command(
            target_name,
            restore_store_name=restore_store_name,
            missing_sentinel_name=missing_sentinel_name,
        )
