package com.example.demo.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import lombok.Data;

@Entity
@Data
public class TicketOrder {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String departureStation;
    private String arrivalStation;
    private String departureDate;
    private String departureTime;
    private String trainNumber;
    private String carriageType;
    private int numberOfPassengers;
    private String passengersJson;
    private String contactPhone;
    private String passengerName;
    private String passport;
}