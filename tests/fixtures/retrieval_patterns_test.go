package patterns

import (
	"encoding/json"
	"math"
	"testing"
)

func TestSyntaxAndFieldErrorsAreDistinct(t *testing.T) {
	if _, err := ParseObject([]byte(`{oops`)); err != ErrMalformedJSON {
		t.Fatal(err)
	}
	for _, body := range []string{`null`, `[]`, `false`} {
		if _, err := ParseObject([]byte(body)); err != ErrInvalidFields {
			t.Fatal(body, err)
		}
	}
	object, err := ParseObject([]byte(`{"n":1.5,"extra":true}`))
	if err != nil || object["extra"] == nil {
		t.Fatal(object, err)
	}
	if _, err := IntegerField(object["n"], nil, nil); err != ErrInvalidFields {
		t.Fatal(err)
	}
}

func TestIntegerBoundsAndTypes(t *testing.T) {
	low, high := int64(-4), int64(7)
	for _, raw := range []string{`-4`, `7`, `0`} {
		if _, err := IntegerField(json.RawMessage(raw), &low, &high); err != nil {
			t.Fatal(raw, err)
		}
	}
	for _, raw := range []string{`-5`, `8`, `null`, `"3"`, `true`, `3.5`, ``} {
		if _, err := IntegerField(json.RawMessage(raw), &low, &high); err != ErrInvalidFields {
			t.Fatal(raw, err)
		}
	}
}

func TestArithmetic(t *testing.T) {
	for _, item := range [][3]int64{{7, 3, 2}, {-7, 3, -3}, {7, -3, -3}, {-7, -3, 2}, {6, 3, 2}} {
		result, err := FloorDivide(item[0], item[1])
		if err != nil || result != item[2] {
			t.Fatal(item, result, err)
		}
	}
	if _, err := FloorDivide(1, 0); err == nil {
		t.Fatal("zero divisor accepted")
	}
	if _, err := MultiplyChecked(math.MaxInt64, 2); err == nil {
		t.Fatal("overflow accepted")
	}
	if value, err := MultiplyChecked(-9, 5); err != nil || value != -45 {
		t.Fatal(value, err)
	}
}
