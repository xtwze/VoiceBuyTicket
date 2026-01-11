package com.example.demo.repositories;

import com.example.demo.entity.Trip;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.List;

@Repository
public interface TripRepository extends JpaRepository<Trip, Long> {
    List<Trip> findByDepartureStationAndArrivalStationAndDepartureDate(
            String departureStation, String arrivalStation, LocalDate departureTime
    );

    List<Trip> findByDepartureStationAndArrivalStationAndDepartureDateBetween(
            String departureStation, String arrivalStation, LocalDate from, LocalDate to);
}
