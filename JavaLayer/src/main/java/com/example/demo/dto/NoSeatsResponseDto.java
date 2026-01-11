package com.example.demo.dto;

import lombok.Builder;
import lombok.Data;

import java.util.List;

public class NoSeatsResponseDto {
    @Data
    public static class NoSeatsResponse{
        private String status; //"no_seats_on_date" или "no_trips
        private String message;
        private List<AlternativeTripDto> alternatives;

        @Data
        @Builder
        public static class AlternativeTripDto{
            private String date;
            private String time;
            private String trainNumber;
            private String carriageType;
            private int availableSeats;
            private double price;
        }
    }
}
