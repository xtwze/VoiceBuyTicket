package com.example.demo.dto;

import lombok.Builder;
import lombok.Data;

public class TicketOrderResponseDto {
    @Data
    public static class TicketsOrderResponse{
        private String status = "success";
        private String message;
        private String trainNumber;
        private String departureTime;
        private String priceTotal;
        private String passengerName;
        private Long orderId;
    }

}
