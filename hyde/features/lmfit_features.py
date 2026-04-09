from __future__ import annotations

from . import Feature, Option, FeatureRegistry

_WEIGHTING = [
    Option("none", "None"),
    Option("std", "Std Dev"),
    Option("inv_std", "1/Std Dev"),
]

_AUTO_GUESS = [
    Option("auto", "Auto Guess"),
    Option("defaults", "Use Defaults"),
]

_CONSTRAINTS = [
    Option("none", "None"),
]

_OUTPUT_LENGTH = [
    Option("auto", "Auto"),
]

_ERROR_ANALYSIS_LEVELS = [
    Option("0.95", "95%"),
    Option("0.99", "99%"),
]


class LmfitFeatures(FeatureRegistry):
    @classmethod
    def register_all(cls):
        cls.register(Feature("function_path", str, "", label="Function", tab="Function and Data"))
        cls.register(Feature("function_name", str, "", label="Function Name", tab="Function and Data"))
        
        cls.register(Feature("y", str, "", label="Y Data", tab="Function and Data"))
        cls.register(Feature("x", str, None, label="X Data", tab="Function and Data"))
        cls.register(Feature("x_range", tuple, None, tab="Data Options"))
        
        cls.register(Feature("weighting", str, "none", options=_WEIGHTING, tab="Data Options"))
        cls.register(Feature("mask", str, None, tab="Data Options"))
        
        cls.register(Feature("result_name", str, "", label="Result Name", tab="Output Options"))
        cls.register(Feature("output_length", str, "auto", options=_OUTPUT_LENGTH, tab="Output Options"))
        cls.register(Feature("full_graph_range", bool, False, tab="Output Options"))
        cls.register(Feature("residual", str, "", tab="Output Options"))
        cls.register(Feature("textbox", bool, False, tab="Output Options"))
        
        cls.register(Feature("store_residuals", bool, True, tab="Output Options"))
        
        cls.register(Feature("confidence_level", str, "0.95", options=_ERROR_ANALYSIS_LEVELS, tab="Output Options"))
        cls.register(Feature("confidence_coeffs", bool, False, tab="Output Options"))
        cls.register(Feature("confidence_bands", bool, False, tab="Output Options"))
        cls.register(Feature("prediction_bands", bool, False, tab="Output Options"))
        
        cls.register(Feature("covariance", bool, False, tab="Output Options"))
        
        cls.register(Feature("auto_guess", str, "auto", options=_AUTO_GUESS, tab="Coefficients"))
        cls.register(Feature("constraints", str, "none", options=_CONSTRAINTS, tab="Coefficients"))
        
        cls.register(Feature("coefficient_output", str, "", label="Coefficient Wave", tab="Coefficients"))


def register_lmfit_features():
    LmfitFeatures.register_all()