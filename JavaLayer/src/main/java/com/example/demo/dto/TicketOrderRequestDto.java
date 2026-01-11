package com.example.demo.dto;
import jakarta.validation.constraints.*;
import lombok.Data;

import java.util.List;

@Data
public class TicketOrderRequestDto {
    @NotBlank(message = "Номер телефона обязателен")
    private String contactPhone;

    @NotBlank
    private String departureStation;

    @NotBlank
    private String arrivalStation;

    @NotBlank
    @Pattern(regexp = "\\d{4}-\\d{2}-\\d{2}", message = "Дата должна быть в формате YYYY-MM-DD")
    private String departureDate;
    private String departureTime;
    private String trainNumber;
    @NotBlank
    private String carriageType;

    @NotNull
    @Min(1)
    @Max(4)
    private Integer numberOfPassengers;

    @NotEmpty
    private List<PassengerTicketDto> passengers;

    @Data
    public static class PassengerTicketDto{
        @NotBlank
        private String ticketType;
    }
}
