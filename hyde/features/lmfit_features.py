from __future__ import annotations

import copy

from hyde.features.base import (
    FeatureCodec,
    normalize_optional_text,
    ordered_unique_text,
    set_path,
    sorted_eligible_names,
    valid_python_identifier,
)

CALCULATED_X_NAME = "_calculated_"


def existing_namespace_names(namespace_view):
    return sorted(str(name) for name in dict(namespace_view or {}))


def unique_preserving_order(values):
    return ordered_unique_text(values)


def x_options(eligible_names):
    return [CALCULATED_X_NAME, *list(eligible_names)]


def fit_argument_expression(argument_name, y_name):
    if argument_name == CALCULATED_X_NAME:
        return f"np.arange(len({y_name}))"
    return str(argument_name)


def command_symbol_names(fit_result_name):
    normalized_name = normalize_optional_text(fit_result_name)
    if normalized_name is None:
        return "_hyde_lmfit_model", "_hyde_lmfit_params"
    base_name = (
        normalized_name[: -len("_result")]
        if normalized_name.endswith("_result")
        else normalized_name
    )
    if not valid_python_identifier(base_name):
        return "_hyde_lmfit_model", "_hyde_lmfit_params"
    return f"{base_name}_model", f"{base_name}_params"


def fit_report_line(fit_result_name):
    normalized_name = normalize_optional_text(fit_result_name)
    if not valid_python_identifier(normalized_name):
        return ""
    return f"print({normalized_name}.fit_report())"


def coefficient_argument_expression(row):
    expression = normalize_optional_text(row.get("expr"))
    if expression is not None:
        return expression
    initial_value = row.get("value")
    if initial_value is None:
        return ""
    return repr(initial_value)


def parse_optional_float(text, field_name):
    stripped = str(text or "").strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid number.") from exc


def fit_result_default_name(y_name, existing_names):
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


def attached_display_label(result_name, component):
    normalized_result_name = normalize_optional_text(result_name)
    if normalized_result_name is None:
        raise ValueError("Curve Fit attached displays require a fit result name.")
    if component == "best_fit":
        return normalized_result_name
    if component == "residual":
        return f"{normalized_result_name}_residuals"
    raise ValueError(f"Unsupported attached display component: {component!r}.")


def restore_target_command(
    target_name,
    *,
    restore_store_name="_hyde_lmfit_live_restore",
    missing_sentinel_name="_hyde_lmfit_missing",
):
    normalized_target_name = normalize_optional_text(target_name)
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


def store_target_command(
    target_name,
    *,
    restore_store_name="_hyde_lmfit_live_restore",
    missing_sentinel_name="_hyde_lmfit_missing",
):
    normalized_target_name = normalize_optional_text(target_name)
    if normalized_target_name is None:
        return ""
    return "\n".join(
        [
            f"{missing_sentinel_name} = globals().get({missing_sentinel_name!r}, object())",
            f"globals()[{missing_sentinel_name!r}] = {missing_sentinel_name}",
            f"{restore_store_name} = globals().setdefault({restore_store_name!r}, {{}})",
            f"if {normalized_target_name!r} not in {restore_store_name}:",
            (
                f"    {restore_store_name}[{normalized_target_name!r}] = globals().get("
                f"{normalized_target_name!r}, {missing_sentinel_name})"
            ),
        ]
    )


class LmfitCodec(FeatureCodec):
    feature_name = "lmfit"
    _valid_commands = {
        "commit",
        "preview",
        "live",
        "store_target",
        "restore_target",
    }

    @classmethod
    def default_state(cls):
        return {
            "feature": cls.feature_name,
            "command": "commit",
            "settings": {
                "fit_function_name": None,
                "y_name": None,
                "x_names": {},
                "from_target": False,
                "coefficients": {},
                "weighting_name": None,
                "fit_result_name": None,
                "fit_result_name_locked": False,
                "preview_target_name": None,
                "target_name": None,
                "previous_target_name": None,
                "restore_store_name": "_hyde_lmfit_live_restore",
                "missing_sentinel_name": "_hyde_lmfit_missing",
            },
            "ui": {},
        }

    @classmethod
    def normalize_state(cls, state):
        normalized = copy.deepcopy(cls.default_state())
        if state:
            normalized["feature"] = state.get("feature", normalized["feature"])
            normalized["command"] = state.get("command", normalized["command"])
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
                    "initial_value": normalize_optional_text(
                        dict(values or {}).get("initial_value")
                    ),
                    "vary": bool(dict(values or {}).get("vary", True)),
                    "lower_bound": normalize_optional_text(
                        dict(values or {}).get("lower_bound")
                    ),
                    "upper_bound": normalize_optional_text(
                        dict(values or {}).get("upper_bound")
                    ),
                    "expr": normalize_optional_text(dict(values or {}).get("expr")),
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
        fit_result_name = settings.get("fit_result_name")
        settings["fit_result_name"] = (
            None if fit_result_name in (None, "") else str(fit_result_name).strip()
        )
        settings["fit_result_name_locked"] = bool(
            settings.get("fit_result_name_locked")
        )
        settings["preview_target_name"] = normalize_optional_text(
            settings.get("preview_target_name")
        )
        settings["target_name"] = normalize_optional_text(settings.get("target_name"))
        settings["previous_target_name"] = normalize_optional_text(
            settings.get("previous_target_name")
        )
        settings["restore_store_name"] = (
            normalize_optional_text(settings.get("restore_store_name"))
            or "_hyde_lmfit_live_restore"
        )
        settings["missing_sentinel_name"] = (
            normalize_optional_text(settings.get("missing_sentinel_name"))
            or "_hyde_lmfit_missing"
        )
        return normalized

    @classmethod
    def validate_state(cls, state):
        normalized = cls.normalize_state(state)
        if normalized["feature"] != cls.feature_name:
            raise ValueError(f"Expected feature={cls.feature_name!r}.")
        command = normalized["command"]
        if command not in cls._valid_commands:
            raise ValueError(f"Unsupported lmfit command: {command!r}.")
        settings = normalized["settings"]
        if command == "preview" and not settings["preview_target_name"]:
            raise ValueError("Lmfit preview requires settings.preview_target_name.")
        if command in {"store_target", "restore_target"} and not settings["target_name"]:
            raise ValueError(f"Lmfit {command} requires settings.target_name.")
        return normalized

    @classmethod
    def update_state(cls, state, action):
        normalized = cls.normalize_state(state)
        action_type = action.get("type")
        if action_type == "set_command":
            normalized["command"] = action["command"]
        elif action_type == "set":
            set_path(normalized, action["path"], action["value"])
        elif action_type == "clear":
            set_path(normalized, action["path"], None)
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
        trace_y_names = unique_preserving_order(
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
            options = x_options(eligible_names)
            if current_name in options and current_name not in used_names:
                value = current_name
            else:
                preferred = None
                if from_target and trace_records and index == 0:
                    preferred = trace_records[0].get("x_name")
                    if preferred is None:
                        preferred = CALCULATED_X_NAME
                if preferred in options and preferred not in used_names:
                    value = preferred
                else:
                    remaining = [
                        name for name in options if name not in used_names
                    ]
                    value = next(
                        (
                            name
                            for name in remaining
                            if name != CALCULATED_X_NAME
                        ),
                        None if not remaining else remaining[0],
                    )
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
        return fit_result_default_name(
            y_name,
            existing_namespace_names(context.get("namespace_view")),
        )

    @classmethod
    def _coefficient_rows(cls, normalized, entry):
        stored_rows = dict(normalized["settings"].get("coefficients", {}))
        rows = []
        for parameter_name in entry.get("parameters", []):
            stored = dict(stored_rows.get(parameter_name, {}))
            expr = normalize_optional_text(stored.get("expr"))
            rows.append(
                {
                    "name": str(parameter_name),
                    "initial_value": normalize_optional_text(
                        stored.get("initial_value")
                    )
                    or "",
                    "vary": bool(stored.get("vary", True)),
                    "lower_bound": normalize_optional_text(
                        stored.get("lower_bound")
                    )
                    or "",
                    "upper_bound": normalize_optional_text(
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
        lowered_coefficients,
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
        if not valid_python_identifier(fit_result_name):
            return {
                "valid": False,
                "message": "Fit-result target must be a valid Python identifier.",
            }
        if not lowered_coefficients["valid"]:
            return {"valid": False, "message": lowered_coefficients["message"]}
        return {"valid": True, "message": ""}

    @classmethod
    def _resolved_weighting_name(cls, normalized, eligible_names):
        weighting_name = normalized["settings"].get("weighting_name")
        return weighting_name if weighting_name in eligible_names else ""

    @classmethod
    def _lowered_coefficients(cls, coefficient_rows):
        lowered_rows = []
        for row in coefficient_rows:
            parameter_name = row["name"]
            expression = normalize_optional_text(row.get("expr"))
            if expression is not None:
                lowered_rows.append(
                    {
                        "name": parameter_name,
                        "expr": expression,
                        "value": None,
                        "vary": False,
                        "lower_bound": None,
                        "upper_bound": None,
                    }
                )
                continue
            initial_value = row.get("initial_value", "")
            if not str(initial_value or "").strip():
                return {
                    "valid": False,
                    "message": f"Parameter {parameter_name} requires an initial value.",
                    "rows": [],
                }
            try:
                initial_number = parse_optional_float(
                    initial_value,
                    f"Parameter {parameter_name} initial value",
                )
                lower_bound = parse_optional_float(
                    row.get("lower_bound"),
                    f"Parameter {parameter_name} lower bound",
                )
                upper_bound = parse_optional_float(
                    row.get("upper_bound"),
                    f"Parameter {parameter_name} upper bound",
                )
            except ValueError as exc:
                return {
                    "valid": False,
                    "message": str(exc),
                    "rows": [],
                }
            if lower_bound is not None and upper_bound is not None and lower_bound > upper_bound:
                return {
                    "valid": False,
                    "message": (
                        f"Parameter {parameter_name} lower bound must be "
                        "less than or equal to the upper bound."
                    ),
                    "rows": [],
                }
            if lower_bound is not None and initial_number < lower_bound:
                return {
                    "valid": False,
                    "message": (
                        f"Parameter {parameter_name} initial value must be "
                        "greater than or equal to the lower bound."
                    ),
                    "rows": [],
                }
            if upper_bound is not None and initial_number > upper_bound:
                return {
                    "valid": False,
                    "message": (
                        f"Parameter {parameter_name} initial value must be "
                        "less than or equal to the upper bound."
                    ),
                    "rows": [],
                }
            lowered_rows.append(
                {
                    "name": parameter_name,
                    "expr": None,
                    "value": initial_number,
                    "vary": bool(row.get("vary", True)),
                    "lower_bound": lower_bound,
                    "upper_bound": upper_bound,
                }
            )
        return {"valid": True, "message": "", "rows": lowered_rows}

    @classmethod
    def _parameter_add_lines(cls, lowered_coefficients):
        lines = []
        for row in lowered_coefficients:
            parameter_name = row["name"]
            if row.get("expr") is not None:
                lines.append(
                    "_hyde_lmfit_params.add("
                    f"{parameter_name!r}, expr={row['expr']!r})"
                )
                continue
            arguments = [
                f"{parameter_name!r}",
                f"value={row['value']!r}",
                f"vary={bool(row.get('vary', True))!r}",
            ]
            if row.get("lower_bound") is not None:
                arguments.append(f"min={row['lower_bound']!r}")
            if row.get("upper_bound") is not None:
                arguments.append(f"max={row['upper_bound']!r}")
            lines.append(f"_hyde_lmfit_params.add({', '.join(arguments)})")
        return lines

    @classmethod
    def _preview_argument_lines(cls, lowered_coefficients):
        arguments = []
        for row in lowered_coefficients:
            expression = coefficient_argument_expression(row)
            if not expression:
                return []
            arguments.append(f"{row['name']}={expression}")
        return arguments

    @classmethod
    def _command_preview(
        cls,
        entry,
        y_name,
        x_rows,
        fit_result_name,
        lowered_coefficients,
        weighting_name,
        *,
        include_report=True,
    ):
        if entry is None:
            return ""
        callable_ref = str(entry.get("callable_ref") or entry["name"])
        model_name, params_name = command_symbol_names(fit_result_name)
        lines = [
            f"{model_name} = lmfit.Model({callable_ref}, "
            f"independent_vars={list(entry.get('independent_vars', []))!r})"
        ]
        parameter_lines = cls._parameter_add_lines(lowered_coefficients)
        if parameter_lines:
            lines.append(f"{params_name} = lmfit.Parameters()")
            lines.extend(
                line.replace("_hyde_lmfit_params", params_name)
                for line in parameter_lines
            )
        if (
            y_name
            and fit_result_name
            and valid_python_identifier(fit_result_name)
            and all(row.get("value") for row in x_rows)
            and lowered_coefficients
        ):
            fit_arguments = []
            if parameter_lines:
                fit_arguments.append(f"params={params_name}")
            fit_arguments.extend(
                (
                    f"{row['name']}="
                    f"{fit_argument_expression(row['value'], y_name)}"
                )
                for row in x_rows
            )
            if weighting_name:
                fit_arguments.append(f"weights={weighting_name}")
            lines.append(
                f"{fit_result_name} = {model_name}.fit("
                f"{y_name}, {', '.join(fit_arguments)})"
            )
            if include_report:
                lines.append(fit_report_line(fit_result_name))
        return "\n".join(lines)

    @classmethod
    def _equation_preview(cls, entry):
        if entry is None:
            return ""
        source_text = str(entry.get("source_text") or "").strip()
        if source_text:
            return source_text
        arguments = list(entry.get("independent_vars", [])) + list(
            entry.get("parameters", [])
        )
        return f"{entry['name']}({', '.join(arguments)})"

    @classmethod
    def _preview_command(
        cls,
        entry,
        y_name,
        x_rows,
        fit_result_name,
        lowered_coefficients,
        preview_target_name,
    ):
        if entry is None:
            return ""
        normalized_preview_target = normalize_optional_text(preview_target_name)
        if normalized_preview_target is None:
            return ""
        if (
            not y_name
            or not fit_result_name
            or not all(row.get("value") for row in x_rows)
        ):
            return ""
        callable_ref = str(entry.get("callable_ref") or entry["name"])
        preview_arguments = cls._preview_argument_lines(lowered_coefficients)
        if not preview_arguments:
            return ""
        independent_arguments = [
            f"{row['name']}={fit_argument_expression(row['value'], y_name)}"
            for row in x_rows
        ]
        return "\n".join(
            [
                f"{normalized_preview_target} = type('_HydeLmfitPreview', (), {{}})()",
                (
                    f"{normalized_preview_target}.best_fit = {callable_ref}("
                    f"{', '.join(independent_arguments + preview_arguments)})"
                ),
                (
                    f"{normalized_preview_target}.residual = {y_name} - "
                    f"{normalized_preview_target}.best_fit"
                ),
            ]
        )

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
        if not command_preview or not valid_python_identifier(fit_result_name):
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
        lowered_coefficients = cls._lowered_coefficients(coefficient_rows)
        weighting_name = cls._resolved_weighting_name(normalized, eligible_names)
        fit_result_name = cls._resolved_fit_result_name(normalized, context, y_name)
        existing_names = existing_namespace_names(context.get("namespace_view"))
        fit_result_options = unique_preserving_order(existing_names + [fit_result_name])
        validation = cls._validate_configuration(
            entry,
            y_name,
            x_rows,
            fit_result_name,
            lowered_coefficients,
        )
        return {
            "fit_function_entry": entry,
            "from_target": from_target,
            "fit_function_name": None if entry is None else entry["name"],
            "y_options": y_options,
            "y_name": y_name,
            "x_rows": x_rows,
            "coefficient_rows": coefficient_rows,
            "lowered_coefficients": lowered_coefficients["rows"],
            "weighting_options": [""] + list(eligible_names),
            "weighting_name": weighting_name,
            "fit_result_name": fit_result_name,
            "fit_result_options": fit_result_options,
            "commands_preview": cls._command_preview(
                entry,
                y_name,
                x_rows,
                fit_result_name,
                lowered_coefficients["rows"],
                weighting_name,
                include_report=True,
            ),
            "equation_preview": cls._equation_preview(entry),
            "valid": bool(validation["valid"]),
            "status_message": validation["message"],
        }

    @classmethod
    def state_to_python(cls, state, context=None):
        normalized = cls.validate_state(state)
        settings = normalized["settings"]
        command = normalized["command"]
        if command == "commit":
            return cls.state_to_commit_python(normalized, context=context)
        if command == "preview":
            return cls.state_to_preview_python(
                normalized,
                context=context,
                preview_target_name=settings["preview_target_name"],
            )
        if command == "live":
            return cls.state_to_live_python(
                normalized,
                context=context,
                previous_target_name=settings["previous_target_name"],
                restore_store_name=settings["restore_store_name"],
                missing_sentinel_name=settings["missing_sentinel_name"],
            )
        if command == "store_target":
            return cls.state_to_store_target_python(
                settings["target_name"],
                restore_store_name=settings["restore_store_name"],
                missing_sentinel_name=settings["missing_sentinel_name"],
            )
        if command == "restore_target":
            return cls.state_to_restore_target_python(
                settings["target_name"],
                restore_store_name=settings["restore_store_name"],
                missing_sentinel_name=settings["missing_sentinel_name"],
            )
        raise ValueError(f"Unsupported lmfit command: {command!r}.")

    @classmethod
    def state_to_commit_python(cls, state, context=None):
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
        include_report=False,
        previous_target_name=None,
        restore_store_name="_hyde_lmfit_live_restore",
        missing_sentinel_name="_hyde_lmfit_missing",
    ):
        presented = cls.present_state(state, context=context)
        return cls._live_command_preview(
            cls._command_preview(
                presented["fit_function_entry"],
                presented["y_name"],
                presented["x_rows"],
                presented["fit_result_name"],
                presented["lowered_coefficients"],
                presented["weighting_name"],
                include_report=bool(include_report),
            ),
            presented["fit_result_name"],
            previous_target_name=previous_target_name,
            restore_store_name=restore_store_name,
            missing_sentinel_name=missing_sentinel_name,
        )

    @classmethod
    def state_to_preview_python(
        cls,
        state,
        context=None,
        *,
        preview_target_name,
    ):
        presented = cls.present_state(state, context=context)
        return cls._preview_command(
            presented["fit_function_entry"],
            presented["y_name"],
            presented["x_rows"],
            presented["fit_result_name"],
            presented["lowered_coefficients"],
            preview_target_name,
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

    @classmethod
    def state_to_store_target_python(
        cls,
        target_name,
        *,
        restore_store_name="_hyde_lmfit_live_restore",
        missing_sentinel_name="_hyde_lmfit_missing",
    ):
        return store_target_command(
            target_name,
            restore_store_name=restore_store_name,
            missing_sentinel_name=missing_sentinel_name,
        )
