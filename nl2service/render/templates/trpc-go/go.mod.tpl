module {{ module_path }}

go 1.22

require (
{% if kafka_enabled %}
	github.com/Shopify/sarama v1.38.1
	github.com/rogpeppe/go-internal v1.12.0 // indirect
	trpc.group/trpc-go/trpc-database/kafka v1.0.0
{% endif %}
	trpc.group/trpc-go/trpc-go v1.0.3
)
