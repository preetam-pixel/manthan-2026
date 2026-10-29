# Architecture migration map

```text
Kafka market.ticks -> market_data.consumer -> strategy.sma ----                                                               v
Kafka market.news -> news.consumer (log/score only)          risk.manager
                                                               |
                                                               v
                                                        execution.client
                                                               |
                                                               v
                                                         POST /orders

REST stocks / portfolio -> portfolio.state
preflight_tick -> app lifecycle -> POST /bot/heartbeat
read-only state -> frontend dashboard
```

Initial migration should preserve original event-loop behavior. Isolate I/O and improve heartbeat responsiveness without silently changing contracts.
