package birdeye

import (
	"context"
	"strings"
	"sync"
	"time"
)

// 分表 schema 快取與併發請求合併（single-flight）。
//
// 背景：Analyser 的結果快取以 (sql, db_id) 為鍵。已認證的呼叫者只要變更 SQL 字面值，
// 就會持續未命中，並使每個涉及的資料表各對 Permission API 的 /api/zta/columns 查詢一次，
// 使平台負載隨請求速率線性成長。本檔將 schema 查詢以 (db_id, schema, table) 為鍵獨立快取，
// 使「換 SQL 字面值」不再觸發重複查詢。
//
// 設計要點：
//   - 沿用 Analyser 之 cacheTTL，故 schema 過期之最長時間與既有結果快取相同，不會更長。
//   - 僅快取成功回應；錯誤不快取（平台暫時故障不致被固定為「無此表」）。
//   - 成功但無欄位（查無此表）採較短之負向 TTL，並受筆數上限約束，
//     避免以不存在之表名繞過快取或撐大記憶體。
//   - 鍵不分大小寫（SQL Server 預設定序不分大小寫），避免以改變大小寫之表名繞過快取。
//   - 併發之相同鍵共用同一次查詢；查詢以脫離呼叫者取消之 context 執行（HTTP 客戶端另有逾時），
//     使單一呼叫者逾時／取消不會把錯誤傳給其他等候者。
const (
	negativeSchemaTTL     = 30 * time.Second
	defaultSchemaCacheMax = 4096
)

type schemaKey struct {
	db            int
	schema, table string
}

type schemaEntry struct {
	cols []SchemaColumn
	at   time.Time
	ttl  time.Duration
}

type schemaCall struct {
	done chan struct{}
	cols []SchemaColumn
	err  error
}

type schemaCache struct {
	fetch SchemaFetcher
	ttl   time.Duration
	max   int
	now   func() time.Time

	mu       sync.Mutex
	entries  map[schemaKey]schemaEntry
	inflight map[schemaKey]*schemaCall
}

func newSchemaCache(fetch SchemaFetcher, ttl time.Duration) *schemaCache {
	return &schemaCache{
		fetch:    fetch,
		ttl:      ttl,
		max:      defaultSchemaCacheMax,
		now:      time.Now,
		entries:  map[schemaKey]schemaEntry{},
		inflight: map[schemaKey]*schemaCall{},
	}
}

// get 具有 SchemaFetcher 之簽章。回傳之 slice 為共用，呼叫端不得修改。
func (c *schemaCache) get(ctx context.Context, dbID int, schema, table string) ([]SchemaColumn, error) {
	if c.ttl <= 0 {
		return c.fetch(ctx, dbID, schema, table) // 與 Analyser 一致：ttl<=0 表示不快取
	}
	key := schemaKey{dbID, strings.ToUpper(schema), strings.ToUpper(table)}

	c.mu.Lock()
	if e, ok := c.entries[key]; ok && c.now().Sub(e.at) < e.ttl {
		c.mu.Unlock()
		return e.cols, nil
	}
	call, running := c.inflight[key]
	if !running {
		call = &schemaCall{done: make(chan struct{})}
		c.inflight[key] = call
		go c.run(ctx, key, call, dbID, schema, table)
	}
	c.mu.Unlock()

	select {
	case <-call.done:
		return call.cols, call.err
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func (c *schemaCache) run(ctx context.Context, key schemaKey, call *schemaCall, dbID int, schema, table string) {
	cols, err := c.fetch(context.WithoutCancel(ctx), dbID, schema, table)

	c.mu.Lock()
	delete(c.inflight, key)
	if err == nil {
		ttl := c.ttl
		if len(cols) == 0 && negativeSchemaTTL < ttl {
			ttl = negativeSchemaTTL
		}
		c.store(key, schemaEntry{cols: cols, at: c.now(), ttl: ttl})
	}
	call.cols, call.err = cols, err
	close(call.done)
	c.mu.Unlock()
}

// store 於持有 c.mu 時呼叫。超過上限時先清除已過期者，仍超過則隨機淘汰約四分之一。
func (c *schemaCache) store(key schemaKey, e schemaEntry) {
	if len(c.entries) >= c.max {
		now := c.now()
		for k, v := range c.entries {
			if now.Sub(v.at) >= v.ttl {
				delete(c.entries, k)
			}
		}
		if len(c.entries) >= c.max {
			drop := c.max / 4
			for k := range c.entries {
				if drop <= 0 {
					break
				}
				delete(c.entries, k)
				drop--
			}
		}
	}
	c.entries[key] = e
}
