package patterns

import (
	"encoding/json"
	"strconv"
	"strings"
)

// IntegerField validates presence, lexical integer type and inclusive bounds.
// A missing/null/string/boolean/fractional/out-of-range field is a field error,
// not a JSON syntax error. Optional fields are handled by the caller first.
func IntegerField(raw json.RawMessage, minimum, maximum *int64) (int64, error) {
	value, err := strconv.ParseInt(strings.TrimSpace(string(raw)), 10, 64)
	if err != nil {
		return 0, ErrInvalidFields
	}
	if minimum != nil && value < *minimum {
		return 0, ErrInvalidFields
	}
	if maximum != nil && value > *maximum {
		return 0, ErrInvalidFields
	}
	return value, nil
}
