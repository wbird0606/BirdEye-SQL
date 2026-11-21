package birdeye

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// countingFetch 回傳固定欄位並記錄每個 (schema, table) 被查詢之次數。
type countingFetch struct {
	mu    sync.Mutex
	calls map[string]int
	total atomic.Int64
	delay time.Duration
	cols  func(schema, table string) ([]SchemaColumn, error)
}

func newCountingFetch() *countingFetch {
	return &countingFetch{calls: map[string]int{}, cols: func(_, _ string) ([]SchemaColumn, error) {
		return []SchemaColumn{{"ProductID", "int"}, {"Name", "nvarchar"}}, nil
	}}
}

func (f *countingFetch) fn(ctx context.Context, _ int, schema, table string) ([]SchemaColumn, error) {
	f.total.Add(1)
	f.mu.Lock()
	f.calls[schema+"."+table]++
	f.mu.Unlock()
	if f.delay > 0 {
		time.Sleep(f.delay)
	}
	return f.cols(schema, table)
}

func (f *countingFetch) count(k string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.calls[k]
}

// 核心情境：變更 SQL 字面值使結果快取持續未命中，但 schema 查詢不應重複。
func TestSchemaCache_VaryingLiteralsFetchSchemaOnce(t *testing.T) {
	f := newCountingFetch()
	a := NewAnalyser(f.fn, time.Minute)
	for i := 0; i < 200; i++ {
		sql := fmt.Sprintf("SELECT ProductID FROM SalesLT.Product WHERE ProductID = %d", i)
		if _, err := a.GetIntents(context.Background(), sql, 2, nil); err != nil {
			t.Fatal(err)
		}
	}
	if n := f.count("SalesLT.Product"); n != 1 {
		t.Fatalf("200 條不同 SQL 應只查詢 schema 1 次，實際 %d 次", n)
	}
}

// 以不同大小寫之表名不得繞過快取。
func TestSchemaCache_CaseVariantsShareEntry(t *testing.T) {
	f := newCountingFetch()
	a := NewAnalyser(f.fn, time.Minute)
	for _, tb := range []string{"SalesLT.Product", "saleslt.product", "SALESLT.PRODUCT", "SalesLT.pRoDuCt"} {
		if _, err := a.GetIntents(context.Background(), "SELECT ProductID FROM "+tb, 2, nil); err != nil {
			t.Fatal(err)
		}
	}
	if n := f.total.Load(); n != 1 {
		t.Fatalf("大小寫變體應共用快取，實際查詢 %d 次", n)
	}
}

// 併發之相同新 SQL 只應查詢一次（single-flight）。
func TestSchemaCache_ConcurrentSingleFlight(t *testing.T) {
	f := newCountingFetch()
	f.delay = 50 * time.Millisecond
	a := NewAnalyser(f.fn, time.Minute)
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			sql := fmt.Sprintf("SELECT ProductID FROM SalesLT.Product WHERE ProductID = %d", i) // 每個 SQL 皆不同
			if _, err := a.GetIntents(context.Background(), sql, 2, nil); err != nil {
				t.Error(err)
			}
		}(i)
	}
	wg.Wait()
	if n := f.count("SalesLT.Product"); n != 1 {
		t.Fatalf("100 個併發請求應合併為 1 次查詢，實際 %d 次", n)
	}
}

// 不同資料庫、不同表不得互相污染。
func TestSchemaCache_KeyIsolation(t *testing.T) {
	f := newCountingFetch()
	c := newSchemaCache(f.fn, time.Minute)
	ctx := context.Background()
	c.get(ctx, 1, "dbo", "A")
	c.get(ctx, 2, "dbo", "A")
	c.get(ctx, 1, "dbo", "B")
	c.get(ctx, 1, "sales", "A")
	if f.total.Load() != 4 {
		t.Fatalf("四個不同鍵應各查一次，實際 %d", f.total.Load())
	}
	c.get(ctx, 1, "dbo", "A")
	if f.total.Load() != 4 {
		t.Fatalf("重複之鍵不應再查詢")
	}
}

// 錯誤不得快取：平台暫時故障後須能恢復。
func TestSchemaCache_ErrorsNotCached(t *testing.T) {
	f := newCountingFetch()
	fail := true
	f.cols = func(_, _ string) ([]SchemaColumn, error) {
		if fail {
			return nil, errors.New("platform down")
		}
		return []SchemaColumn{{"ProductID", "int"}}, nil
	}
	c := newSchemaCache(f.fn, time.Minute)
	ctx := context.Background()
	if _, err := c.get(ctx, 2, "SalesLT", "Product"); err == nil {
		t.Fatal("應回傳錯誤")
	}
	fail = false
	cols, err := c.get(ctx, 2, "SalesLT", "Product")
	if err != nil || len(cols) != 1 {
		t.Fatalf("故障排除後應取得 schema：%v %v", cols, err)
	}
}

// 查無此表（成功但空）採負向快取，且 TTL 不超過 negativeSchemaTTL。
func TestSchemaCache_NegativeCachedWithShortTTL(t *testing.T) {
	f := newCountingFetch()
	f.cols = func(_, _ string) ([]SchemaColumn, error) { return nil, nil }
	c := newSchemaCache(f.fn, 300*time.Second)
	now := time.Unix(1_000_000, 0)
	c.now = func() time.Time { return now }
	ctx := context.Background()
	for i := 0; i < 5; i++ {
		c.get(ctx, 2, "dbo", "NoSuchTable")
	}
	if f.total.Load() != 1 {
		t.Fatalf("負向結果應被快取，實際查詢 %d 次", f.total.Load())
	}
	now = now.Add(negativeSchemaTTL + time.Second) // 遠小於 300 秒
	c.get(ctx, 2, "dbo", "NoSuchTable")
	if f.total.Load() != 2 {
		t.Fatalf("負向快取應於 %v 後過期", negativeSchemaTTL)
	}
}

// 一般結果之 TTL 與 Analyser 一致：過期後重新查詢（schema 異動最終生效）。
func TestSchemaCache_ExpiresAfterTTL(t *testing.T) {
	f := newCountingFetch()
	c := newSchemaCache(f.fn, 300*time.Second)
	now := time.Unix(1_000_000, 0)
	c.now = func() time.Time { return now }
	ctx := context.Background()
	c.get(ctx, 2, "SalesLT", "Product")
	now = now.Add(299 * time.Second)
	c.get(ctx, 2, "SalesLT", "Product")
	if f.total.Load() != 1 {
		t.Fatalf("TTL 內不應重查")
	}
	now = now.Add(2 * time.Second)
	c.get(ctx, 2, "SalesLT", "Product")
	if f.total.Load() != 2 {
		t.Fatalf("超過 TTL 應重查，以反映 schema 異動")
	}
}

// ttl<=0 維持「不快取」語意。
func TestSchemaCache_ZeroTTLDisablesCaching(t *testing.T) {
	f := newCountingFetch()
	c := newSchemaCache(f.fn, 0)
	for i := 0; i < 3; i++ {
		c.get(context.Background(), 2, "dbo", "T")
	}
	if f.total.Load() != 3 {
		t.Fatalf("ttl<=0 不應快取，實際查詢 %d 次", f.total.Load())
	}
}

// 以大量不存在之表名不得使快取無限成長。
func TestSchemaCache_BoundedSize(t *testing.T) {
	f := newCountingFetch()
	f.cols = func(_, _ string) ([]SchemaColumn, error) { return nil, nil }
	c := newSchemaCache(f.fn, time.Minute)
	c.max = 100
	for i := 0; i < 5000; i++ {
		c.get(context.Background(), 2, "dbo", fmt.Sprintf("Rand%d", i))
	}
	c.mu.Lock()
	n := len(c.entries)
	c.mu.Unlock()
	if n > c.max {
		t.Fatalf("快取筆數 %d 超過上限 %d", n, c.max)
	}
}

// 呼叫者取消不得把錯誤傳給其他等候者，且查詢仍完成並被快取。
func TestSchemaCache_CallerCancelDoesNotPoisonWaiters(t *testing.T) {
	f := newCountingFetch()
	f.delay = 100 * time.Millisecond
	c := newSchemaCache(f.fn, time.Minute)

	ctx1, cancel1 := context.WithCancel(context.Background())
	started := make(chan struct{})
	go func() {
		close(started)
		c.get(ctx1, 2, "SalesLT", "Product") // 發起者，隨即取消
	}()
	<-started
	time.Sleep(10 * time.Millisecond)

	res := make(chan error, 1)
	go func() {
		cols, err := c.get(context.Background(), 2, "SalesLT", "Product") // 等候者
		if err == nil && len(cols) == 0 {
			err = errors.New("空結果")
		}
		res <- err
	}()
	time.Sleep(10 * time.Millisecond)
	cancel1()

	if err := <-res; err != nil {
		t.Fatalf("等候者不應受發起者取消影響：%v", err)
	}
	if f.total.Load() != 1 {
		t.Fatalf("應仍只查詢 1 次，實際 %d", f.total.Load())
	}
}

// 呼叫者自身之 context 取消時須即時返回。
func TestSchemaCache_CallerContextHonored(t *testing.T) {
	f := newCountingFetch()
	f.delay = 300 * time.Millisecond
	c := newSchemaCache(f.fn, time.Minute)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err := c.get(ctx, 2, "SalesLT", "Product")
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("應回傳 DeadlineExceeded，實際 %v", err)
	}
	if time.Since(start) > 200*time.Millisecond {
		t.Fatalf("未即時返回")
	}
}
