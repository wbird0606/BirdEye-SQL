package birdeye

import (
	"bytes"
	"encoding/json"
	"fmt"
)

// omap 是保留 key 順序的 JSON 物件（mermaid exporter 需要，對照 Python dict）。
type omap struct {
	keys []string
	m    map[string]any
}

func (o *omap) get(k string) (any, bool) {
	v, ok := o.m[k]
	return v, ok
}

// parseOrderedJSON 把 JSON 字串解析成保留物件 key 順序的結構：
// 物件 → *omap、陣列 → []any、其餘為 string / float64 / bool / nil。
func parseOrderedJSON(s string) (any, error) {
	dec := json.NewDecoder(bytes.NewReader([]byte(s)))
	dec.UseNumber()
	v, err := readOrderedValue(dec)
	if err != nil {
		return nil, err
	}
	return v, nil
}

func readOrderedValue(dec *json.Decoder) (any, error) {
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	return readOrderedFrom(dec, tok)
}

func readOrderedFrom(dec *json.Decoder, tok json.Token) (any, error) {
	switch t := tok.(type) {
	case json.Delim:
		switch t {
		case '{':
			o := &omap{m: map[string]any{}}
			for dec.More() {
				kt, err := dec.Token()
				if err != nil {
					return nil, err
				}
				key := kt.(string)
				val, err := readOrderedValue(dec)
				if err != nil {
					return nil, err
				}
				o.keys = append(o.keys, key)
				o.m[key] = val
			}
			if _, err := dec.Token(); err != nil { // '}'
				return nil, err
			}
			return o, nil
		case '[':
			var arr []any
			for dec.More() {
				val, err := readOrderedValue(dec)
				if err != nil {
					return nil, err
				}
				arr = append(arr, val)
			}
			if _, err := dec.Token(); err != nil { // ']'
				return nil, err
			}
			if arr == nil {
				arr = []any{}
			}
			return arr, nil
		}
		return nil, fmt.Errorf("unexpected delim %v", t)
	case json.Number:
		f, _ := t.Float64()
		return f, nil
	default:
		return tok, nil // string, bool, nil
	}
}
