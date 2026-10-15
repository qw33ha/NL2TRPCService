// Generic patterns: adapt the error status mapping to the approved endpoint IR.
package patterns

import (
	"encoding/json"
	"errors"
)

var ErrMalformedJSON = errors.New("malformed JSON")
var ErrInvalidFields = errors.New("invalid fields")

// ParseObject separates malformed JSON from valid JSON of an invalid shape.
// RawMessage preserves field types until independent validation. Unknown fields
// remain available; the caller enforces its explicit allow/reject policy.
func ParseObject(body []byte) (map[string]json.RawMessage, error) {
	if !json.Valid(body) {
		return nil, ErrMalformedJSON
	}
	var object map[string]json.RawMessage
	if err := json.Unmarshal(body, &object); err != nil || object == nil {
		return nil, ErrInvalidFields
	}
	return object, nil
}
