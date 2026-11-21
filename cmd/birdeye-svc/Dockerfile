# birdeye-svc（Go）—— 對照 Python birdeye-svc/。純 Go 映像，取代 Flask 版。
# build context 需為 repo 根目錄（COPY birdeye-go/）。
FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY birdeye-go/ .
RUN CGO_ENABLED=0 GOOS=linux go build -o birdeye-svc ./cmd/birdeye-svc

FROM alpine:3.20
WORKDIR /app
RUN apk add --no-cache ca-certificates
COPY --from=builder /build/birdeye-svc .
ENV PORT=8001
EXPOSE 8001
CMD ["/app/birdeye-svc"]
