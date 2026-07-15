module {{ module_path }}

go 1.22

require (
{% if kafka_enabled %}
	github.com/Shopify/sarama v1.38.1
	trpc.group/trpc-go/trpc-database/kafka v1.0.0
{% endif %}
{% if db_enabled and db_type == "mysql" %}
	trpc.group/trpc-go/trpc-database/mysql v1.0.0
{% endif %}
{% if db_enabled and db_type == "postgres" %}
	gorm.io/gorm v1.23.5
	trpc.group/trpc-go/trpc-database/gorm v1.0.0
{% endif %}
	github.com/rogpeppe/go-internal v1.12.0 // indirect
	trpc.group/trpc-go/trpc-go v1.0.3
)
