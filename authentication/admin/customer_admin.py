from django.contrib import admin


class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "bio",
        "birth_date",
        "address",
    )
    search_fields = (
        "id",
        "address",
    )
    list_filter = ("birth_date",)
