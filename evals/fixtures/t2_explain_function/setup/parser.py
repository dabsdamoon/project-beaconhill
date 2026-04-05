def parse_csv_line(line: str, delimiter: str = ",") -> list[str]:
    fields: list[str] = []
    current = ""
    in_quotes = False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
        elif char == delimiter and not in_quotes:
            fields.append(current.strip())
            current = ""
        else:
            current += char
    fields.append(current.strip())
    return fields
