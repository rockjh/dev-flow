"""Literal-only shared resource parsing; no names inferred from variables."""
import re


def sql_resources(sql):
    if not isinstance(sql, str) or re.search(r"--|/\*|;\s*\S", sql):
        return []
    # Values may contain SQL words; they never name source objects.  Deliberate
    # narrow subset: no CTEs, subqueries, comma joins or quoted identifiers.
    sql = re.sub(r"'(?:''|[^'])*'", "''", sql)
    if re.search(r'["`\[\]]|\$\{|\b(?:WITH|USING)\b', sql, re.I):
        return []
    operation = re.match(r"\s*(SELECT|INSERT|UPDATE|DELETE)\b", sql, re.I)
    if not operation:
        return []
    if len(re.findall(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", sql, re.I)) != 1:
        return []
    from_clause = re.search(r"\bFROM\b(.*?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|$)", sql, re.I)
    if from_clause and "," in from_clause[1]:
        return []
    object_name = r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?![\w.\-])"
    patterns = {"SELECT": r"\b(?:FROM|JOIN)\s+" + object_name, "INSERT": r"\bINTO\s+" + object_name,
                "UPDATE": r"^\s*UPDATE\s+" + object_name, "DELETE": r"\bFROM\s+" + object_name}
    names = re.findall(patterns[operation[1].upper()], sql, re.I)
    return [(name, "read" if operation[1].upper() == "SELECT" else operation[1].lower()) for name in dict.fromkeys(names)]
