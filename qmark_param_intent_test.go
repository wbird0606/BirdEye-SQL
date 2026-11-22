package birdeye

import "testing"

// qmark 模式下位置參數顯示為 "?"，不得被當成欄位而產生 FILTER／READ 意圖
// （否則帶參數之 WHERE 會因找不到名為 "?" 之欄位權限而被代理拒絕）。
func TestQmarkParameterProducesNoColumnIntent(t *testing.T) {
	reg := NewMetadataRegistry()
	if err := reg.LoadFromCSV("table_schema,table_name,column_name,data_type\nSalesLT,Product,ProductID,int\nSalesLT,Product,Name,nvarchar\n"); err != nil {
		t.Fatal(err)
	}
	res, err := NewRunner(reg).RunMulti("SELECT Name FROM SalesLT.Product WHERE ProductID > ? AND Name <> ?", []any{700, "x"})
	if err != nil {
		t.Fatal(err)
	}
	intents, err := NewIntentExtractor().ExtractFromStr(res.JSON)
	if err != nil {
		t.Fatal(err)
	}
	for _, in := range intents {
		if in.Column != nil && *in.Column == "?" {
			t.Fatalf("placeholder leaked as column intent: %+v", in)
		}
	}
	want := map[string]bool{"READ:Name": false, "FILTER:ProductID": false, "FILTER:Name": false}
	for _, in := range intents {
		if in.Column != nil {
			want[in.Intent+":"+*in.Column] = true
		}
	}
	for k, ok := range want {
		if !ok {
			t.Errorf("missing intent %s", k)
		}
	}
}
