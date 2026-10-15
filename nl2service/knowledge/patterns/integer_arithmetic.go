package patterns

import (
	"errors"
	"math"
)

var ErrArithmetic = errors.New("invalid integer arithmetic")

// MultiplyChecked avoids overflow in integer business expressions.
func MultiplyChecked(left, right int64) (int64, error) {
	if (left == math.MinInt64 && right == -1) || (right == math.MinInt64 && left == -1) {
		return 0, ErrArithmetic
	}
	result := left * right
	if right != 0 && result/right != left {
		return 0, ErrArithmetic
	}
	return result, nil
}

// FloorDivide implements mathematical floor, including negative operands.
// For nonnegative inputs ordinary integer division already rounds down.
func FloorDivide(numerator, denominator int64) (int64, error) {
	if denominator == 0 || (numerator == math.MinInt64 && denominator == -1) {
		return 0, ErrArithmetic
	}
	quotient, remainder := numerator/denominator, numerator%denominator
	if remainder != 0 && ((remainder < 0) != (denominator < 0)) {
		quotient--
	}
	return quotient, nil
}
